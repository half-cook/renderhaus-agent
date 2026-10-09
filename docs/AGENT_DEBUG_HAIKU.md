# Haiku agent debug handoff

This branch fixes the nine failures from the supplied lighthouse run and changes the default
manager and every subagent to `anthropic:claude-haiku-5-5`. No live provider calls, push,
PR, deployment, authentication bypass, or copied research/third-party skill occurred.
Comet is unavailable; browser E2E and the operator's live rerun remain incomplete.

The evidence trails are [agent decisions](agent-debug-decisions.tsv),
[model decisions](agent-debug-haiku-model-decisions.tsv), and
[routing decisions](routing-debug-decisions.tsv). Installed Deep Agents 0.7.23 governed
implementation. Reviews ran in isolated native-agent worktrees; offline restrictions prevented
external-model review lanes.

## Behavior and tools

ElevenLabs HTTP TTS now honors `ELEVENLABS_DRY_RUN` alone. Shots and clips require a completed
render with a usable URL or a nonempty local artifact; ffprobe checks duration and a video stream
when installed. Deliverable length parsing ignores timing cues, supports hyphenated/numeric/word
forms, and never imposes video duration on speech. Plain shot + voiceover uses video, then
ElevenLabs, then final MP4 assembly. Input frames/references preserve i2v/r2v. A named video
provider affects the video step rather than blocking the audio step. Assembly/export is distinct
from an NLE ZIP handoff.

No provider generation tools were added. The existing eight providers, 81 Gateway tools and
24 skills remain. The local MCP gateway adds the standard search tool
`x_amz_bedrock_agentcore_search(query, limit=8)` and exposes provider schemas progressively;
`limit` is 1–20. Calls still use `Provider___verb` and the registry's typed contracts.
An optional spend cap blocks unknown estimates and reserves concurrent calls before dispatch.

Existing `Remotion___render_timeline(title, visuals, audio_tracks, aspect_ratio, fps,
output_filename, ...)` accepts a plain `output_path` instead of `url` for each visual/audio
source. Local assembly returns a queued `render_id`, then
`Remotion___get_render_progress(render_id, bucket_name="local")` returns the MP4 `output_path`
on completion. Its supported features and limits are in [local setup](LOCAL_ASSEMBLY.md).
Lambda remains the production default. Dry-run defaults and approval/spend gates remain.

The manager emits the validated `StudioAgentOutput` completion tool using automatic tool choice.
Two bounded repair attempts can recover missing final output; repair cannot dispatch providers.
Context reads return routed rows, saved references/jobs and discovered names; a named tool argument
requests its full schema. System prompts and bound-tool ordering stay stable on approval resume.
For supported preserved-thinking models, history remains append-only and automatic summarization
is disabled. Static role dispatch wrappers are bound once; exact Gateway schemas still require search.
Provider calls log estimated cost/latency; model turns log usage and estimated first-party cost.

## Configuration

No new secrets or dry-run flags are required. Existing `ANTHROPIC_API_KEY` and
`ELEVENLABS_API_KEY` remain the relevant provider credentials; do not add them to git.
Set `RENDERHAUS_AGENT_MODEL=anthropic:claude-haiku-5-5` explicitly if Secrets Manager still has
an old `AGENT_MODEL`. Global `RENDERHAUS_AGENT_EFFORT` remains optional.

New optional model/effort suffixes are `PLANNER`, `MEDIA`, `AUDIO`, `EDITOR`, and
`GENERAL_PURPOSE`, e.g. `RENDERHAUS_AGENT_MODEL_PLANNER` and
`RENDERHAUS_AGENT_EFFORT_PLANNER`. Manager/planner/general-purpose default to medium;
media/audio/editor default to low. AgentCore forwarding and secret synchronization accept these
non-secret settings. Sampling parameters are omitted; supported models use adaptive thinking.

New local settings are `REMOTION_RENDER_BACKEND=lambda|local` (default lambda) and
`REMOTION_LOCAL_MEDIA_HOSTS` (comma-separated exact trusted public HTTPS hosts, default empty).
Local assembly needs installed ffmpeg/ffprobe, `RENDERHAUS_MEDIA_DIR` for shared source/output files,
and an explicit `REMOTION_DRY_RUN=false` to run local compute. No generation is enabled by that
setting. Existing `AGENTCORE_GATEWAY_ALLOW_LOOPBACK_HTTP=true` enables the loopback gateway.

## Prices and licences

Sources were read 2026-10-09. No price was invented and provider logs describe estimates rather
than reconciled invoice cost. Stripe-enabled ElevenLabs calls still require operator-configured
`ELEVENLABS_TOOL_COST_CENTS_JSON`. Without Stripe, official speech character rates supply approvals.

| Item | Price / licence decision | Primary source |
| --- | --- | --- |
| Haiku 5.5, <=100k prompt | $0.10 input / $0.50 output / $0.125 5m cache write / $0.01 cache read per MTok | https://platform.claude.com/docs/en/models/haiku-5-5/overview |
| Haiku 5.5, >100k prompt | $0.50 / $2.50 / $0.625 / $0.05 per MTok | Same overview and https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide |
| Eleven v4 Turbo | v4 $0.08/1k characters × 0.5 multiplier = $0.04/1k; promo $0.011/1k through 2026-10-12, then automatic expiry | https://elevenlabs.io/pricing/api |
| Local ffmpeg assembly | $0 provider charge; operator supplies compute | https://ffmpeg.org/legal.html |
| Lambda / unknown operations | TODO / unknown unless operator quote supplied; never inferred free in approvals | TODO: no verified per-call quote |
| Claude models | Proprietary commercial API; competing-model training blocked, training eligibility false | https://www.anthropic.com/legal/commercial-terms |
| Eleven v4 Turbo | Paid commercial API; authorized voice inputs; no clear training grant, training eligibility remains false | https://elevenlabs.io/terms-of-use |
| Existing Wan/Seedream and other models | Existing licence/consent/training gates retained; no new weights, model adapters or licence grants | `agent/deep_agent/routing_policy.json` source URLs |
| Remotion / ffmpeg | Existing Remotion commercial obligations; system ffmpeg is LGPL/GPL depending on build, no vendoring or AGPL introduced | https://www.remotion.dev/docs/license ; https://ffmpeg.org/legal.html |

## Routing gates and remaining work

RT-152/153/154 are active ordered Wan → ElevenLabs → assembled-MP4 fixtures. Forbidden still
tools are filtered before binding/discovery/disclosure/dispatch for those requests. RT-156 is an
active named Seedream route. RT-155 separately proves generic stills block automatic Seedream;
its GPT Image expectation remains expected-failure: `pending feat/provider-openai-images`.
The full lighthouse brief and follow-up assemble prompt are committed fixtures. Thirty-eight
existing routing rows remain skipped for their recorded pending-provider/integration reasons;
no pending provider was activated by this task.

Remaining work: Comet Studio approval/rejection and playback validation; operator live lighthouse
rerun; real Haiku cache savings and signed-thinking API behavior; compatibility of ElevenLabs
non-TTS variants with the selected model; pending image/music/specialist adapters. Preserved
history can reach context limits; fresh-thread compaction needs a separate explicit design.
Local rendering supports a subset of Lambda effects and trusts operator-configured remote hosts;
DNS validation and HTTP resolution are separate, so configured hosts must be trustworthy.

## Review and verification

Independent native reviews covered routing/discovery, model runtime/configuration, provider costs,
artifact delivery, local rendering and gateway boundaries. Accepted findings were fixed and
re-tested, including named-provider scoping, I2V/R2V preservation, nested search payloads,
completion-repair timeout, partial-render detection, unknown spend estimates, and ffprobe timeouts.
The comment review removed seven narration lines, restored none and left no MUST KILL flags
or unenforced constraint comments. External protocol/licence/pricing references were preserved.

The starting baseline was 852 tests with 40 skips. Final discovery passed: **883 tests,
40 skipped, one expected failure (RT-155)**. Ruff, ci_check and the Studio typecheck passed.
Final verification is recorded in ignored
`.renderhaus/e2e/`: full unittest discovery, Ruff, ci_check and Studio TypeScript checks. All
provider dry-run flags were true and `RENDERHAUS_SECRETS_NAME` was empty for required checks.
Synthetic local assembly tests explicitly enable only local ffmpeg compute; HTTP provider tests
use mocks. A recorded browser receipt has status `blocked`; it is not a passed E2E receipt.

No Studio source changed. Typechecking used the provided temporary node_modules symlink, which
was removed afterward. Provider/tool/skill thresholds stay 8/81/24 in deployment and Docker;
only the routing fixture threshold rises to 129 total / 91 unskipped rows (one expected failure).

## Implementation commits

| Hash | Change |
| --- | --- |
| `3e2195d` | fix(elevenlabs): let the dry-run flag govern default TTS HTTP calls |
| `fa51d97` | fix(agent): require real rendered media for shot and clip delivery |
| `889fdc4` | fix(billing): quote offline TTS from official character prices |
| `5716f8e` | feat(observability): record provider cost estimates and call latency |
| `a3338e9` | docs: record TTS pricing evidence and offline validation decisions |
| `6ff2344` | Fix deliverable duration and ordered shot voiceover routing |
| `cd17205` | fix(gateway): filter excluded still tools before search disclosure and dispatch |
| `a8347cf` | fix(agent): route supplied sessions from the current request prompt |
| `f5acf11` | Add exact RT-152 through RT-156 routing gates and named-provider fixtures |
| `9cea7b1` | fix(billing): disclose zero provider charge for local assembly |
| `c374be7` | Route plain make and create shot requests as video |
| `7d58cff` | Add offline local Remotion assembly with typed media handoff |
| `adafe0c` | Add loopback Gateway with progressive search and optional spend guard |
| `3699f99` | Disclose supported local assembly features in Gateway schema |
| `7894d44` | Document local media handoff and current capability defaults |
| `8afef6b` | Reject malformed render URLs during artifact validation |
| `2f603da` | Block unconfirmed local Gateway spend estimates before dispatch |
| `8207307` | Preserve video modality and scope narration dispatch and tool discovery |
| `3ec6c30` | Switch Deep Agents to Haiku with stable prompts and validated completion |
| `f687dd0` | Keep unpriced model telemetry costs explicitly unknown |
| `6bfa012` | Require persisted successful render exit and complete MP4 duration |
| `16af51c` | Align spend and delivery fixtures with telemetry and artifact validation |
| `f5ee032` | Align contract fixtures with explicit still routing and stable tools |
| `0eff7b7` | Return failed local renders when output probing times out |
| `5d98aa7` | Remove redundant narration after comment review |
| `4823364` | Align manager audio guidance with capability routing |

The final documentation commit records the verification result and this handoff.

## Changed files

- `AGENTS.md`
- `agent/backend_config.py`
- `agent/deep_agent/memory.py`
- `agent/deep_agent/routing.py`
- `agent/deep_agent/routing_policy.json`
- `agent/deep_agent/runner.py`
- `agent/deep_agent/skills/audio-bed/SKILL.md`
- `agent/deep_agent/skills/final-assembly/SKILL.md`
- `agent/deep_agent/skills/image-gen/SKILL.md`
- `agent/deep_agent/skills/still-then-video/SKILL.md`
- `agent/deep_agent/skills/t2v/SKILL.md`
- `agent/deep_agent/usage.py`
- `agent/gateway_executor.py`
- `agent/studio_agent_next.py`
- `configs/gateway/remotion.tools.json`
- `docs/AGENT_DEBUG_HAIKU.md`
- `docs/DEEP_AGENT.md`
- `docs/ELEVENLABS.md`
- `docs/LOCAL_ASSEMBLY.md`
- `docs/SKILLS.md`
- `docs/agent-debug-decisions.tsv`
- `docs/agent-debug-haiku-model-decisions.tsv`
- `docs/routing-debug-decisions.tsv`
- `providers/contracts.py`
- `providers/elevenlabs/api.py`
- `providers/registry.py`
- `providers/remotion/api.py`
- `providers/remotion/local.py`
- `providers/remotion/local_worker.py`
- `scripts/ci_check.py`
- `scripts/deploy_agentcore.py`
- `scripts/local_gateway.py`
- `scripts/sync_secrets.py`
- `server/billing_rates.py`
- `server/config.py`
- `tests/fixtures/skill_routing.json`
- `tests/test_agent_model_config.py`
- `tests/test_agentcore_gateway.py`
- `tests/test_autonomous_spending.py`
- `tests/test_codex_harness.py`
- `tests/test_deep_agent.py`
- `tests/test_deep_agent_contract.py`
- `tests/test_deep_agent_usage.py`
- `tests/test_delivery_routing.py`
- `tests/test_elevenlabs_cost_estimate.py`
- `tests/test_elevenlabs_routing_model.py`
- `tests/test_hyperframes.py`
- `tests/test_local_assembly.py`
- `tests/test_local_gateway.py`
- `tests/test_local_render_cost.py`
- `tests/test_provider_cost_logging.py`
- `tests/test_provider_ladder.py`
- `tests/test_request_context.py`
- `tests/test_request_tool_exclusions.py`
- `tests/test_skill_routing.py`
- `tests/test_video_delivery_artifacts.py`
- `tests/test_vidu_q4_routing.py`
