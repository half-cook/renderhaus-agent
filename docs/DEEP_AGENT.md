# Studio Deep Agents backend

Word-level footage corrections use [dialogue-edit](DIALOGUE_EDIT.md) on existing sync-3.
Preview and video each pause for consent/cost approval; ambiguous preview creation cannot
be automatically retried. The flow uses the existing media dispatch and native approval resume.

Renderhaus uses `deepagents==0.7.23` by default. One chat handles planning, media generation,
refinement, and final Remotion assembly. Canvas references are optional. The existing Studio
request, job, approval, progress, asset, and conversation contracts remain in place.

## Configuration

| Variable | Behavior |
| --- | --- |
| `RENDERHAUS_AGENT_BACKEND` | `deepagents` by default; `codex` selects the retained app-server backend. Other values fail explicitly. |
| `RENDERHAUS_AGENT_MODEL` | LangChain `provider:model`, default `anthropic:claude-sonnet-5-5`. Supported prefixes are `anthropic`, `openai`, `bedrock`, and `bedrock_converse`. Unknown prefixes and empty model IDs fail explicitly. |
| `RENDERHAUS_AGENT_EFFORT` | Anthropic effort, default `medium` for manager/planner/general-purpose and `low` for media/audio/editor. Accepts `low`, `medium`, `high`, `xhigh`, or `max`; maps to `output_config.effort`. Ignored for OpenAI, Bedrock, Codex, and injected test models. |
| `RENDERHAUS_AGENT_MODEL_<ROLE>` | Optional override for `PLANNER`, `MEDIA`, `AUDIO`, `EDITOR`, or `GENERAL_PURPOSE`; falls back to the global model. |
| `RENDERHAUS_AGENT_EFFORT_<ROLE>` | Optional matching effort override; falls back to the global effort, then the role default. |
| `AGENT_MODEL` | Explicit legacy fallback when the new model variable is absent or blank. Unqualified names and `openai/` names select OpenAI. Codex still uses this variable and defaults to `gpt-5.6-luna`. |
| `RENDERHAUS_AGENT_TIMEOUT_SECONDS` | Graph execution deadline, default 1800 seconds. |
| `STUDIO_MEDIA_WAIT_SECONDS` | Host polling deadline per provider job, default 600 seconds. |
| `CHAT_STORY_LOOKALIKE_THEMES` | `off` by default. Literal `on` enables neutral lookalike presets only for explicit user requests after legal sign-off. The agent cannot enable it. |
| Provider `*_DRY_RUN` variables | Keep their existing provider behavior. The agent cannot change configuration. Dry runs never satisfy video delivery. |

Satya chose Claude Sonnet 5.5 after Haiku 5.5 for the manager and every subagent. Manager, planner and
research roles use medium effort for decisions across multiple steps. Media, audio and editor
roles use low effort for focused dispatch. Set a role override such as
`RENDERHAUS_AGENT_MODEL_PLANNER=anthropic:claude-opus-5-5` to change the planner independently.
The global model applies to the manager and inherited role models.
The global effort overrides every role default unless that role has its own setting. Set
`RENDERHAUS_AGENT_MODEL=openai:gpt-5.6-luna` to select the previous default. Selection reads the
first nonblank value of `RENDERHAUS_AGENT_MODEL`, then `AGENT_MODEL`, then the Sonnet default.
Studio no longer injects a legacy `AGENT_MODEL` value that would mask this default.

These effort choices are workload defaults, not measured Sonnet quality claims.
Medium leaves the manager and planner room for dependency and approval decisions.
Low keeps focused media, audio and editor dispatch responsive. Both retain adaptive thinking.
Anthropic recommends medium for multistep tool use and low for scoped work on its
[effort page](https://platform.claude.com/docs/en/build-with-claude/effort), read 2026-10-09.
Live effort calibration remains pending because this branch was tested offline.

Anthropic uses `ANTHROPIC_API_KEY`; OpenAI uses `OPENAI_API_KEY`. A missing selected-provider
key prevents model construction with an error naming the required environment variable.
Importing configuration and injecting a fake chat model require no keys. Provider media
dry-run flags do not make a real planning-model invocation free or offline. Bedrock uses the
deployment's IAM credential chain and configured AWS region. Studio readiness checks the
selected provider; Bedrock readiness does not probe AWS or prove model access. The Studio
server and AgentCore worker must use matching backend, model, and effort configuration.

### Verified model contract and pricing

Anthropic's [Sonnet 5.5 overview](https://platform.claude.com/docs/en/models/sonnet-5-5/overview),
read 2026-10-09, verifies `claude-sonnet-5-5`, a 1M context window and 128K output limit.
Adaptive thinking runs by default. The API effort default is high; Renderhaus sets medium or low explicitly.

The [migration guide](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide),
read 2026-10-09, rejects manual `thinking: {type: enabled, budget_tokens: ...}` and assistant
prefill with HTTP 400. Sonnet accepts `adaptive` and `between_tools`; `disabled` is rejected.
`between_tools` accepts only low, medium or high effort and no additional thinking fields.
Renderhaus uses `adaptive`. The supported efforts are low, medium, high, xhigh and max.
The [legacy thinking guide](https://platform.claude.com/docs/en/build-with-claude/extended-thinking)
and [thinking steering guide](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost)
were also read 2026-10-09.

Non-default temperature, top_p and top_k return HTTP 400 on Sonnet 5.5. The integration omits
all three. Adaptive thinking and effort are sent only to the supported adaptive allowlist.
Sonnet 5.5 rejects forced `tool_choice` of `any` or a named `tool`, including without up-front
thinking. Opus 5.5 also rejects both, as confirmed by its
[migration guide](https://platform.claude.com/docs/en/models/opus-5-5/migration-guide), read 2026-10-09.
The manager exposes `StudioAgentOutput` as a normal tool and keeps automatic choice, following
the [tool-choice contract](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools),
read 2026-10-09. Mocked SDK HTTP verifies the complete graph sends supported settings and
finishes without forced-choice warnings. The existing append-only middleware retains signed thinking history.

First-party list prices per million tokens come from Anthropic's
[official pricing page](https://platform.claude.com/docs/en/about-claude/pricing), read 2026-10-09.

| Model / prompt length | Input | Output | 5m cache write | 1h cache write | Cache read |
| --- | --- | --- | --- | --- | --- |
| Haiku 5.5, <=100k | $0.10 | $0.50 | $0.125 | $0.20 | $0.01 |
| Haiku 5.5, >100k | $0.50 | $2.50 | $0.625 | $1.00 | $0.05 |
| Opus 5.5 | $4.00 | $20.00 | $5.00 | $8.00 | $0.20 |
| Sonnet 5.5 | $2.00 | $10.00 | $2.50 | $4.00 | $0.10 |

Haiku's threshold counts uncached input, cache reads and cache writes for each call, rather
than the aggregate turn total. Thinking tokens are already included in output usage.
`agent.deep_agent.usage` emits `agent_model_usage` JSON records with the run scope, model,
call count, token totals, estimated list cost and unknown-cost call count, including subagents
and approval resumes. It records completed messages once by message ID. These estimates use
duration-specific cache writes and first-party rates. Sonnet has no long-context price tier.
Batch input/output receive a 50% discount; US-only inference has a 1.1 multiplier.
Renderhaus's standard Messages requests use global routing, without those modifiers.
Partner hosts, discounts and taxes require separate pricing. Unknown models have no invented rate.
No live model invocation was performed.

The [lighthouse operator driver](E2E_LIGHTHOUSE.md) defaults to a plan-only run and
supports a $5 cap shared by model and media calls for an explicitly authorized live run.
It was tested with fake models and provider dispatch only.

Claude is a proprietary commercial API under the
[Anthropic Commercial Terms](https://www.anthropic.com/legal/commercial-terms), read 2026-10-09.
The terms assign output rights to the customer and restrict training competing models.
Renderhaus treats planning output as `training_eligible=false`; it does not enter media
continuity training. No model weights, AGPL code, or non-commercial code are added.

### AgentCore and Lambda configuration

Store `ANTHROPIC_API_KEY` in the existing `renderhaus/app` Secrets Manager JSON secret, or
provide it through the local process environment. `scripts/sync_secrets.py` accepts this key
and the non-secret model and effort settings through its existing generic payload filter.
The runtime's execution role already reads that application secret. No key belongs in
Docker build arguments, a workflow default, tool schemas, prompts, or logs.

AgentCore bootstrap configuration forwards `RENDERHAUS_AGENT_BACKEND`,
`RENDERHAUS_AGENT_MODEL`, `RENDERHAUS_AGENT_EFFORT`, and both settings for all five roles when supplied. The deployment preflight
checks the selected provider instead of requiring an OpenAI key for every model. Its code is
validated offline; no deployment is performed by this change. Existing Secrets Manager values
override bootstrap settings, so a stored `AGENT_MODEL` continues to select the legacy model
until an explicit `RENDERHAUS_AGENT_MODEL` overrides it or that legacy value is removed.

Provider Gateway Lambdas do not run the planning model and need no new model setting or
Anthropic credential for this feature. Their schemas, dry-run flags, tool counts, and approvals
remain governed by the existing creative-provider configuration.

## Reasoning and tool execution

`agent/studio_agent_next.py` owns public Pydantic contracts, Studio context, Gateway billing,
asset handles, output validation, and the AgentCore SSE entrypoint. `run_studio_agent()` selects
the backend. An explicitly injected Codex harness selects Codex for existing callers and tests.
`agent/deep_agent/runner.py` compiles `create_deep_agent` with the configured model, native
skills, role-specific subagents, memory, virtual files, checkpointer, and HITL middleware.
The explicit `StudioAgentOutput` completion tool validates the existing downloadable Markdown
schema and ends the manager turn. Automatic tool choice avoids the framework's forced-tool
warning. If the model ends without valid output, the host appends at most two repair requests.
During repair, only the completion tool can execute, so no paid action or delegation repeats.

The configured Anthropic model is constructed lazily with LangChain `init_chat_model` before
Gateway discovery. Supported adaptive models receive `thinking={"type": "adaptive"}` and `output_config.effort`.
Other provider strings retain Deep Agents' native initialization, including OpenAI Responses
API defaults. `langchain-anthropic==1.7.5` is already a pinned project dependency.

Manager and subagent prompts have stable prefixes. Routes, render jobs and changed project
memory enter appended user messages. Skills metadata is cached for a conversation and bodies
are read on demand. The small role dispatch wrappers remain bound in a fixed order; exact
Gateway provider tools still require discovery and policy validation. For preserved-thinking
Anthropic models, the host replaces client summarization by name with append-only history.
Long conversations can therefore reach a provider context limit; start a new conversation
rather than editing signed history. Other models retain native summarization.

Installed Deep Agents 0.7.23 orders `SkillsMiddleware`, `AnthropicPromptCachingMiddleware`,
then memory in the manager stack. Child stacks put caching after skills; they read project
memory as file data rather than injecting changing memory into their system prompt. The
integration preserves native cache controls. The offline approval-resume regression compares
serialized system messages, full tool schema lists and the previous message prefix. It proves
prefix stability, while live cache savings remain for the operator's rerun.

`GatewayExecutor` is shared by both backends. It validates the discovered MCP schema, reuses
completed call IDs, refuses replacement renders while a saved render is active, restores exact
bucket/output identifiers, polls a single accepted job, registers media, and publishes Studio
progress. `GatewayMCPServer` remains the only remote provider boundary. It resolves asset
handles, charges/refunds usage, and preserves the existing authenticated HTTPS MCP transport.

Deep Agents exposes `report_progress`, `read_studio_context`, `record_media_outcome`, and Gateway semantic search.
The manager binds `call_media_tool`, `call_audio_tool`, and `call_editor_tool` in a stable order.
Roles bind only their allowed wrapper. Read the relevant skill before using it.
These tools accept the exact discovered Gateway name and an argument object.
`read_studio_context` returns routed capability rows and discovered names. Its optional
`tool_name` argument returns one already discovered schema; it never dumps the full catalog. Discovery returns
actual schemas, including tools hidden from the initial catalog behind semantic search. Unsupported or
undiscovered tools fail without dispatch. Discovery itself does not need a spending approval.

The installed `langchain-mcp-adapters==0.3.1` imports MCP 1's `mcp.server.fastmcp`. This project's
installed MCP 2.3.0 has no such module. The backend therefore builds LangChain tools around the
existing MCP client rather than downgrading MCP or bypassing Studio policy. Adapters can replace
this conversion when they support the project's MCP version.

## Capability routing

The quality-first capability map selects an explicit requested provider/model, then a named
exception, then the capability default. Pending or commercially blocked defaults use only declared interims.
Cost estimates support disclosure and approvals, never tier or price ordering. Stored
`confidential` and `quality_tier` project fields do not affect selection or approvals.
The shared executor enforces the same choice on both backends, including approved resumes.
Edit and extend use Seedance 2.5 as permanent defaults through fal US. Neither capability
has an interim or fallback; Wan 3 edit/extend are named-only and retain their preview block.

Demoted generation/edit/image providers remain built and explicit-only through named-provider.
Vidu's archived skill is removed while its Fal tools remain. All paid video pauses with an
estimate even during autonomous runs when the global video-approval switch is enabled.
Only the existing legacy Wan provenance/training retry path retains its special behavior.
See [the capability map](CAPABILITY_MAP.md) and [routing policy](SKILLS.md#capability-selection).

## Skills and delegation

There are 40 packaged `SKILL.md` files under `agent/deep_agent/skills/`.
Deep Agents reads metadata first. Full instructions enter context when a relevant skill is read.
`metadata.include_tools` documents real dispatch wrappers, which are stably bound per role. `metadata.routing_tools` holds
canonical capability/workflow IDs, while `metadata.gateway_tools` lists built names only.
Pending aliases cannot dispatch as Gateway tools. The generated inventory is in
[packaged skills](SKILLS.md#packaged-skills).

The original video-short, product-images, storyboard-shots, audio, final-assembly and refinement
skills remain. Image-gen applies GPT still defaults and Recraft/Ideogram exceptions.
Named-provider honors explicit demoted generation providers. Act-Two and Kling Motion Control
use the act-two skill even for explicit performance requests. Mureka lyrics-video and Topaz finishing are built. Product-demo-video keeps the pending cutaway capture utility;
whiteboard-explainer plans narrated Remotion templates without claiming unsupported marker-hand animation.
The knowledge-explainer plans silent graphic beats and event-timed SFX. Its shared request
guard excludes narration/TTS before approval and dispatch, including on resumes. It reuses
Remotion, explicit HyperFrames previews, Mirelo and ElevenLabs SFX. Existing-clip audio-only
requests retain audio-bed. See [knowledge explainers](KNOWLEDGE_EXPLAINER.md).

Plan-to-video reviews a written plan with per-chapter ElevenLabs narration, decision
cards and silent holds. Its route selects Remotion before generic generation or editing;
HyperFrames requires an explicit request. Source text in quotes, fences or blockquotes
does not choose providers. The agent reads the skill and constructs native timeline
arguments; there is no new compiler or dispatch wrapper. Answers stay separate from the
source plan, and an MP4 hold does not automatically pause playback or authorize coding.
See [plan review videos](PLAN_TO_VIDEO.md).

The deterministic router supplies skill and tool proposals in graph input and Studio context.
For a generated shot with independent narration, `intent_route.execution_groups` puts video
and TTS in the same group and assembly in the following group. The manager discovers both
schemas and any authorized voice before launching media/audio tasks or generation calls
together. TTS dispatch precedes a blocking video poll. Assembly waits for both completed
artifacts. A brief that requires the generated clip's transcript or synchronized Foley
retains that dependency. The scripted real-graph regression verifies dispatch ordering
through the normal approval/resume path; live model compliance remains to be measured.

Final assembly omits `output_resolution` or uses `source` unless the customer requests
`720p`, `1080p`, `1440p`, or `2160p`. The canvas follows the largest measured video short
edge up to the aspect default. A single 1280x720 shot at 16:9 therefore delivers 1280x720.
Choosing a lower Wan resolution produces a lower-resolution deliverable unless an upscale
is requested. This does not change generation defaults or quality-first routing.
The final-assembly skill and project memory require delivered `width` and `height`,
`source_resolution`, and resolution warnings in the summary and Markdown. A larger
requested canvas must disclose "upscaled from 1280x720; no added detail" using the measured
source size. Topaz through the existing upscale skill is the route to actual enhancement.
If no video dimensions can be measured, retain the aspect canvas with an explicit warning.
See [assembly resolution and encoder behavior](LOCAL_ASSEMBLY.md) and
[resolution decisions](fix-assembly-native-resolution-decisions.tsv).

The executor persists a `cost_ledger` keyed by tool call ID in its session snapshot.
Paid attempts retain their list-price estimate across approval resumes and failures;
free tools, rejected approvals and dry runs do not add paid line items. Completion appends
every recorded media step and an estimated total to the final Markdown in stable call-ID
order. The short Studio summary also includes per-step costs when they fit its 320-character
contract; larger runs refer to the complete breakdown. Unknown charges remain explicit,
with a known subtotal. Model token charges are recorded separately by `ModelUsage`.

The capability-map fixture contains 352 retained rows, with 346 active and 6 dependency skips.
Archived/confidential routes are dropped. Active rows cover built tools and declared interims;
pending specialists keep named branch reasons. Editorial overrides retain the safe preparer,
separate rendering approval, and existing export/HyperFrames narration workflow contracts.
See [fixture verification](SKILLS.md#offline-routing-verification) and
[conversational editing](SKILLS.md#conversational-editing-after-generation).

The optional [HyperFrames composition skill](SKILLS.md#optional-hyperframes-compositions)
adds HTML authoring guidance beside Remotion. `HYPERFRAMES_ENABLED=false` and
`HYPERFRAMES_DRY_RUN=true` are its defaults. Deep Agents injects the local
`HyperFrames___render_composition` preview tool only when enabled. It uses the same
editor dispatch, approval, and spending gates; live rendering fails closed until
an isolated worker exists. The [assessment](HYPERFRAMES_ASSESSMENT.md) documents
the Apache adaptation, dependencies, and remaining verification.

The existing skill also packages MIT caption, collage, and Hyfrme
[recipes and HTML examples](HYPERFRAMES_TEMPLATE_PACKS.md). Manager and editor
read their catalog, templates, and references through `/skills/hyperframes/`.
The existing composition input contract and native approval/resume paths apply.
Plain style requests use Remotion. Named HyperFrames requests retain the optional
feature gate. No provider dispatch, secret, or top-level skill is added.
The [Hyfrme pack](HYPERFRAMES_HYFRME_PACK.md) uses the same catalog shape and
native filesystem for three more examples. Only the HyperFrames name selects
the optional renderer. A Hyfrme pack name cannot change routing or approvals.

Fish Audio is not in the current active provider catalog. Its speech tool is usable only when
Gateway discovers an available Fish Audio target. Skills explicitly report unavailable tools.
The model cannot invent a target or call a provider directly.

The `planner` subagent has no provider dispatch. `media` can dispatch only OpenAI/Seedance/Seedream/Kling/Runway/Fal/Luma;
`audio` can dispatch only audio providers; `editor` can dispatch Remotion and the optional HyperFrames tool,
including `Remotion___export_nle_timeline` for the DaVinci Resolve handoff. That export is free and
only packages existing project media, so it is exempt from approval (`APPROVAL_EXEMPT_TOOLS` in
`agent/gateway_executor.py`); every paid tool still follows the native approval policy. The overridden
`general-purpose` subagent also has no provider dispatch. All roles share project files and
read-only Studio context. They inherit native approval policy and have no shell tool.
Each role explicitly receives its configured model and effort. Per-role settings override the
global settings. Injected test models are reused across roles without credentials.
The pure `Remotion___prepare_conversational_edit` requires cut-plan approval even when
autonomous. Its estimate is zero and its preview preserves asset handles. The editor receives
word timestamps from the manager/audio role, which alone can dispatch paid transcription.

The manager and each role explicitly install `TodoListMiddleware`. The installed 0.7.23
graph does not add it automatically. Multi-shot and multi-step requests can track `write_todos`
state across turns, while child todo lists remain separate from the manager plan. Subagent
task results merge only changed files, preventing unchanged sibling snapshots from replacing
another role's edits. Concurrent intentional edits to the same file still need task ownership.

Packaged skill metadata stays frozen for the manager conversation. Start a new conversation
to load changed descriptions or wrapper metadata. Skill bodies remain readable on demand.
Approval resumes retain their checkpointed state. Dispatch wrapper validation runs before the approval predicate; malformed
calls produce normal tool validation feedback, and valid calls keep the same approval policy.

Model text streams into the existing Studio `MODEL_UPDATE` progress events before each
response finishes. Updates accumulate up to the existing 1,000-character limit and complete
under the same event ID. Child namespaces separate progress IDs. Tool arguments, reasoning
blocks, and middleware-internal summary calls do not become customer progress.

See [the 0.7.23 audit](DEEP_AGENT_AUDIT.md) for feature coverage, fixes, and deferred work.

Provider/model licence and region gates live in `routing_policy.json` and are enforced in the
shared executor even after approval. MiniMax H3 and Hunyuan are disabled by default and never
train QC. Only completed Apache Wan provenance can enter the continuity training hook.
The optional `RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS` caps estimated paid spend for one autonomous
job. It is off when unset and requires a stable job ID when enabled. Reservations persist
before submission, share one executor across subagents, and stop unknown-priced or excessive
paid dispatch while allowing job recovery polls. See [Skills and routing](SKILLS.md) for the
policy schema, cached, lazily loaded SigLIP and DINOv2 QC, unconfigured face interface, DINOv3 opt-in DINO slot (off by default; see docs/CONTINUITY_QC_BENCHMARK.md),
and the pending and retired provider references.

## Memory and durable threads

The `CompositeBackend` routes `/skills/` to a virtual, protected filesystem rooted at the
packaged skills directory. Everything else uses `StateBackend`. Model file tools cannot write
shipped skills, execute commands, or access host files. The initial `/AGENTS.md` records the
production rules. It can then hold project direction, plans, asset versions, and job IDs.
`ProjectMemory` retains its initial system prefix. Changed memory enters the next user turn; the upstream middleware caches its
loaded content in checkpoint state.

The thread ID hashes workspace, project, and conversation identity. Execution approval scope
also includes the job ID. Virtual files persist across turns in that project conversation;
separate conversations do not share memory. This is conversation-scoped project memory, not a
cross-conversation project knowledge store.

`StudioCheckpointer` saves LangGraph checkpoints, channel blobs, and pending writes, including
nested subagent tasks. Its versioned JSON snapshot is `renderhaus_deepagents_session` in existing
conversation and execution storage. Bytes are base64 encoded; pickle deserialization is disabled
and constructor types are restricted. Snapshots include engine versions and reject mismatches.
Dependency versions are pinned because the portable format follows LangGraph's saver layout.
A fresh worker restores the same native thread and files from the snapshot.

Local Studio saves checkpoints through `session_sink` after each graph checkpoint or write.
AgentCore streams them in private `kind=checkpoint` SSE messages while the worker runs, and
returns them with completed, approval, and failed results. Studio saves received snapshots and
tool events before waiting for the final result. Final payload hydration reuses the persisted
asset version, so streamed media is registered once. Search and dispatch call IDs include
execution scope to keep job ledgers separate. The progress and result envelopes are unchanged.
A disconnect retains checkpoints and media events that already reached Studio. A remote worker
lost before emitting its latest checkpoint still needs external durable storage or reconciliation. Portable snapshots currently retain checkpoint history;
large, long-lived conversations need retention limits or a durable saver.

## Approval and recovery behavior

Native `interrupt_on` uses a `when` predicate. Paid non-video dispatch pauses in
non-autonomous runs and proceeds under existing spending authorization when autonomous.
All paid video pauses even when autonomous while `premium_video_approval` is enabled.
Topaz finishing, like the existing quality-first generation/avatar tools, always pauses
with cost even when that switch is disabled. Topaz uses measured source properties and
refuses live submission when its published estimate is unknown; see [Topaz](TOPAZ.md).
The shared policy adds a `server.billing_rates.cost_for` estimate to approval descriptions
and visible labels. Unconfirmed prices remain unknown. `RENDERHAUS_PREMIUM_VIDEO_APPROVAL=false`
disables the additional autonomous video pause. ElevenLabs administrative tools still interrupt
in autonomous mode. Existing non-autonomous approval rules remain intact, including free-tool
behavior, and free NLE packaging remains exempt. Only approve/reject decisions are
allowed. Nested and batched interrupts become existing Studio approval cards with exact
provider names, arguments, and stable call IDs.

Approval state binds the workspace/project/conversation/job and native interrupt IDs. Missing
decisions leave the run paused. Rejection records the tool event without contacting Gateway.
Approval resumes with `Command(resume=...)` in a fresh worker; completed calls are not repeated.
A new turn without approval state starts from saved conversation context and does not authorize
an old interrupted call. Existing stop/resume endpoints and provider-job recovery remain intact.

Pending checkpoints cannot move between Codex and Deep Agents. Select the backend that created
the pending approval. Completed legacy history is reference data on the new backend. Start a
new conversation when switching engines to avoid importing large legacy history snapshots.

A provider job accepted before a process crash but not yet persisted can still require
reconciliation. Neither backend supplies an exactly-once distributed execution guarantee.

### Parallel subagent approvals

The installed deepagents 0.7.23 and LangGraph 1.2.14 surface both media and audio
interrupts through the parent task state. The host sends every decision in one
`Command(resume={interrupt_id: {"decisions": [...]}})`. Decisions match their approval
call IDs and retain each interrupt's action order. A fresh worker resumes the original
tool calls before the subagent models receive their results. Rejected calls return
feedback to their subagents while approved siblings dispatch once.

The captured Sonnet Lighthouse failure came from the driver's Gateway client.
`LocalGateway.list_tools` exposes search only. The bare `GatewayClient` forwarded
search results without adding the returned schemas to its tool list. Approved calls
resumed, but the executor returned `Search for this Gateway tool before invoking it.`
before contacting a provider. The models then requested new calls. The trace also
contains two earlier serial voice-search approvals that failed the same way.

The Lighthouse loopback now uses the same `GatewayMCPServer` discovery client as
Studio. It caches searched schemas and supports their restoration from session state.
Its local server uses stateless JSON responses so a prior SSE server's process-wide
shutdown flag cannot terminate the next run. Spend and ledger state stay on `LocalGateway`.
Parallelism, approval IDs, version-1 resume state, cost estimates, and both no-paid-retry
guards retain their existing behavior. No provider or model configuration changes.

Offline regressions exercise the compiled graph, serial approval and rejection, both
mixed parallel decisions, and the real Lighthouse approval loop with loopback MCP.
Models and provider dispatch are scripted. The parallel driver test replaces final
artifact probing to isolate approval and dispatch behavior, so it does not establish
generated-media playback or browser success. Comet validation is blocked because no
controllable Comet session is available and this task prohibits live provider calls.
See [the decisions record](fix-parallel-approvals-decisions.tsv) for reproduction evidence.

## AgentCore and verification

`Dockerfile.agentcore` defaults to Deep Agents and retains Codex for explicit fallback.
It installs pinned dependencies and verifies the Deep Agents version and all 43 packaged
skills during the build. The entrypoint remains `python -m agent.studio_agent_next`.
The existing Studio approval/review surfaces display the edit plan, subtitles, grade and
audio fades. The database schema stays compatible.

Offline checks use the compiled graph with a scripted chat model, the existing Codex localhost
fixtures, provider dry runs, and Studio/AgentCore contract tests. They exercise tool disclosure,
focused delegation, nested/batched approval and rejection, thread and memory recovery, saved
render identifiers, final delivery checks, and the existing server contracts. They do not prove
live model judgment, live provider credentials, generated media playback, or browser behavior.

```bash
export RENDERHAUS_SECRETS_NAME=''
export SEEDANCE_DRY_RUN=true SEEDREAM_DRY_RUN=true ELEVENLABS_DRY_RUN=true
export FISH_AUDIO_DRY_RUN=true REMOTION_DRY_RUN=true
export KLING_DRY_RUN=true RUNWAY_DRY_RUN=true FAL_DRY_RUN=true
export TOPAZ_DRY_RUN=true
export LUMA_DRY_RUN=true HYPERFRAMES_DRY_RUN=true
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/ruff check agent lambdas scripts server providers
.venv/bin/python scripts/ci_check.py
```

Comet browser E2E is blocked in this environment. There is no controllable Comet session, and this task prohibits paid/live provider calls. The blocker is recorded under ignored
`.renderhaus/e2e/` using `scripts/browser_e2e_hook.py`. No live E2E pass is claimed.

## Wan 3 generation on fal

The existing media role and `DISPATCH_TARGETS` already admit Fal tools.
The t2v, i2v and reference_video defaults bind to the three Wan 3 tools.
The existing native `interrupt_on` callbacks pause them before dispatch, with list costs,
including autonomous runs. Approval exemptions and the autonomous spend cap are unchanged.
Real-face consent is checked against both the current prompt and native tool arguments.
See [Wan 3 provider contracts](FAL_WAN3_PROVIDER.md) for schemas and offline validation limits.

## Wan 3 edit and extend on Model Studio

`call_media_tool` dispatches the `ModelStudio` target only for named Wan 3.0 or Model Studio
edit/extend requests. The named-provider skill exposes its real Gateway names and warns that
Alibaba preview terms permit internal testing only until GA. `wan3_edit` and `wan3_extend`
never appear as capability defaults, exceptions or interims. Seedance 2.5 is the permanent
default regardless of Wan's model licence flag. Explicit Luma, Aleph, and VACE remain available.

Paid edit/extend interrupts retain the installed deepagents 0.7.23 checkpointer and
`Command(resume=...)` behavior. Cost descriptions use regional input plus output seconds,
including existing platform fees. Approval/rejection recovery is tested in autonomous runs.
The free poll tool uses the existing job loop at 15-second intervals and persists output.
Training eligibility is false under proprietary service terms.

The default legacy US base URL remains UNVERIFIED for generation and blocked live.
Preview licensing also blocks customer live use on workspace hosts. Configuration,
smart-duration limits, the licence restriction, and blocked Comet E2E are documented
in [the Model Studio provider reference](ALIBABA_MODELSTUDIO.md).

## Seedance 2.5 dialogue exceptions and permanent edit defaults

The Seedance target remains in `DISPATCH_TARGETS.call_media_tool`. Its five generation tools
use the existing callable `interrupt_on` cost descriptions and checkpointer/resume protocol in
installed deepagents 0.7.23. No manager or subagent model changes are part of this upgrade.
The host defaults to fal US and reuses fal polling; saved endpoint provenance survives a
transport configuration change. All Seedance outputs are ineligible for continuity training.

Synthetic dialogue uses the Seedance 2.5 exception for t2v/i2v/reference video. Edit-v2v and
refinement expose the permanent Seedance edit/extend defaults. Extension requires explicit
generated output seconds, integer 4–30, with a measured 2–30 second, 24–60 fps source.
Fal bills input plus requested output seconds, without timeline arithmetic. “Extend by N
seconds” remains refused because source inclusion in the output is UNVERIFIED. Real-person
references force Wan generation with consent and refuse Seedance editing/extension.
Model Studio remains preview-blocked when explicitly named. See
[Seedance contracts, pricing and unresolved limits](SEEDANCE_2_5.md).

## OpenAI still images

`OpenAI___generate_image` and `OpenAI___edit_image` implement the still-image and image-edit
defaults, including text-in-image generation. Edits accept a primary image, up to 15 additional
references, and an optional mask. Results contain saved images synchronously, without polling.
Seedream remains explicit-only. Spending approval and visual approval remain separate.
The OpenAI branch activated eight GPT routing rows.

[OpenAI configuration and verified sources](OPENAI_IMAGES.md) describe the default dry-run flag,
unknown pre-call costs, output training restriction, and blocked Comet validation.

## Sync dispatch and approval

`Sync` is a media-role dispatch target. The converted lipsync skill exposes the media and
audio wrappers for the ElevenLabs TTS → existing-footage sync-3 chain. Manager and subagent
models default to `claude-sonnet-5-5`. The installed deepagents 0.7.23 signatures govern native
`interrupt_on` configuration and `Command(resume=...)`; no custom approval middleware or
provider-side bypass is introduced. `Sync___lipsync_video` always requires native approval,
including autonomous runs with the generic premium-video flag disabled. Approval descriptions
and progress disclosure include host, model, consent subjects and the host-specific quote.
Polling is free. Consent and vendor-policy failures remain refusals after spending approval.
See [SYNC.md](SYNC.md) for terms, pricing and verification limits.


## HeyGen dispatch and consent

`HeyGen` is a media dispatch target. `HeyGen___create_avatar_video` always pauses for native
approval, including autonomous runs and when the premium-video switch is disabled. The existing
0.7.23 Deep Agents `interrupt_on` description includes engine, routing basis, subjects, consent,
cost and upload-use disclosure. Approval/rejection persists through the existing checkpointer
and resumes the original tool arguments on a fresh worker. The shared executor rejects missing
recorded consent before interruption; the provider checks accepted HeyGen consent before POST.

The direct Studio invoke endpoint refuses HeyGen generation so it cannot bypass approval.
Saved poll artifacts finish standalone presenters; captions or assembly require rendering.
`training_eligible=false` follows the model policy even when an outcome claims otherwise.
See [HeyGen](HEYGEN.md).

Mureka music and lyrics-video share the audio role and six Gateway tools. Native
0.7.23 interrupts quote paid video and resume once after approval; rejection performs
no dispatch. This includes autonomous lyrics-video requests. Songs pause unless
autonomous. See [Mureka](MUREKA.md) for transport, pending raw-audio preparation,
licences and blocked browser validation.

Performance transfer uses the installed act-two skill with native cost/consent interrupts on
`call_media_tool`. Long sources process each approved Act-Two chunk sequentially; polls never
submit paid children. The editor uses the existing Remotion concat path. See
[performance transfer](PERFORMANCE_TRANSFER.md). Deep Agents 0.7.23 signatures were inspected
locally; scripted-model approval/resume tests are offline and do not establish live quality.

## Mirelo SFX

`Fal___mirelo_v2a` retains `call_media_tool` and the shared queue poll. SFX 2.0 defaults to an audio bed with `preserve_speech=true`; select its video endpoint for a muxed MP4 or explicitly select legacy 1.6 for A/B. Native cost interrupts still cover approval and rejection even autonomous. Audio-only completion requires a current saved audio version. Video requests require a matching later assembly that uses that bed, or a saved video from the selected video endpoint. Source renders cannot complete pending audio work. See [Mirelo](MIRELO.md) for verified schema/pricing, licence and pending Comet validation.

## Image specialist activation

`Fal___ideogram_edit` serves the text-only existing-image edit exception and
`Fal___recraft_text_to_vector` serves editable SVG/vector output. Both reuse
`Fal___get_video_task`, default to dry-run, quote verified fal image prices and
exclude training. SVG content is validated and sanitized before persistence.
The image-gen, product-images and refinement skills expose their real tool names.
Six specialist fixture rows are active.
Comet validation and Ideogram quality A/B
remain pending. See [Image specialists](IMAGE_SPECIALISTS.md) for contracts,
official sources read 2026-10-09, licence decisions and configuration.

## Experimental Gemini continuity candidate

The continuity skill now includes `Gemini___judge_continuity` and `Gemini___get_task`.
The canonical `gemini_vlm_judge` alias is built and its retained routing row is active.
`local_qc` remains default. The VLM is dry-run by default and promotion requires a complete,
committed, hash-pinned live result above 0.85 on the 420 frozen pairs. No result is committed.
See [Gemini configuration and sources](GEMINI_CONTINUITY_QC.md),
[benchmark procedure](CONTINUITY_QC_BENCHMARK.md#experimental-gemini-judge-and-eval-gate),
and [decisions](continuity-qc-vlm-decisions.tsv). Comet E2E remains blocked.

## Priced ElevenLabs TTS models

The four TTS variants expose only `eleven_v4_turbo` and `eleven_v4`, derived from
`ELEVENLABS_CHARACTER_MULTIPLIERS`. Omitted `model_id` uses `ELEVENLABS_TTS_MODEL`,
defaulting to `eleven_v4_turbo`. Invalid IDs or configured defaults fail with the allowed IDs.
The native Deep Agents 0.7.23 approval predicate and the shared Gateway executor validate TTS
before routing disclosure or interruption. Invalid requests return a normal failed tool result,
so the agent can correct them without an unknown-cost approval card or provider dispatch.
Operator quotes cannot bypass the model allowlist; missing Stripe quotes fail before approval.
HTTP transport, autonomous spend caps, and approval exemptions retain their existing behavior.
See [ElevenLabs](ELEVENLABS.md) and [decisions](fix-tts-model-pin-decisions.tsv).
Scripted lighthouse tests cover correction and known-cost approval offline. Comet E2E and live
audio playback remain blocked by unavailable Comet control and the offline-only task constraint.

## NLE re-import

`resolve-handoff` now imports an editor's FCPXML or OTIO through the free local
`Remotion___import_nle_timeline` tool in the editor role. Import returns a replacement
Remotion assembly and an asset reconciliation report. A blocked import never replaces
the current assembly. A dry-run is only a preview. Successful application uses the
existing project filesystem tools and checkpoint persistence, with the previous assembly
retained for review. The canvas graph and the legacy flat timeline are separate models.

Import retains opaque source handles without publishing or fetching media. No new
provider, model, key, secret, or environment variable is needed. `REMOTION_DRY_RUN`
remains true by default. All existing paid-video approval and spending gates remain.
Read [NLE import](NLE_EXPORT.md#import-an-editors-timeline) for the
parser contract and unsupported edits. Comet and real editor validation remain blocked
or unverified; offline tests do not establish browser success.

## Matrix editing on a local worker

The manager and editor discover `Remotion___render_ad_variants` and `Ffmpeg___ffmpeg_tool`
through `call_editor_tool`. Their aliases are `ad_variant_matrix` and `ffmpeg_tool`.
The [matrix skill](../agent/deep_agent/skills/remotion-ad-variant-matrix/SKILL.md) requires
`plan` before `render_first`, first-output visual review, and approval of that exact plan hash
before `render_batch`. The first and batch calls pause in autonomous mode as well. Planning
is free; approval descriptions disclose render count, aspects, plan hash and a configured
compute/licence estimate. The trusted executor records approval; the agent cannot create
an approval by passing fields in the tool arguments.

Media inspection is free. It runs on the machine owning the confined local job directory,
with fixed ffmpeg/ffprobe executables and a nineteen-op registry. No arbitrary scripts, paths or
arguments enter subprocess commands. Resolve-only requests return a parked refusal before
generic generation or NLE-handoff matching. Existing interchange export remains available
for supported requests. The stored confidential field does not change these routes.

Local timelines now include measured allow-listed text and positioned image/video overlays.
Lambda receives the same document/renderConfig props, but new font/box fields are refused
unless `REMOTION_OVERLAY_CONTRACT_VERSION=2` confirms a separately deployed compatible
composition. This task makes no deployment or Lambda call. Matrix jobs refuse the Lambda
backend until the same job directory exists on its worker. See
[Remotion editing](REMOTION_EDITING.md) for the supported backend table and demo commands.

Ordinary Remotion renders now execute on the configured backend: local worker dispatch
resolves owned asset handles without publishing and confines raw paths to the current job;
Lambda uses the Gateway. Shared preflight refuses unsupported features before media I/O
or AWS submission, including dry-run. Polls use their saved render IDs. Fixed motion/grade
presets, centre rotation and literal SRT captions share the timeline contract. CI checks
structured skill backend/feature claims against the executable capability table. Lambda
parity is payload-level only; deployed rendering and Comet validation remain unverified.

Inventory is 21 providers, 140 Gateway tools and 44 skills. The fixture has 346 active and
6 deferred cases among 352 rows. Browser validation through Comet remains blocked here.

The free local `ffmpeg_tool` adds subtitle burning, SRT export, supplied LUT grading,
audio cleanup and preview proxies. `local_finishing` routes these through the existing
editor dispatcher and delivery or loudness skill. The host validates parameters and every
secondary path before dispatch. No approval exemption, spending cap, paid-video policy or
planner model changes. Run cleanup before loudness measurement and retain final-file QC
for delivery claims. See [local finishing](providers/ffmpeg-finishing.md).

## Per-shot static reframing

The manager reads the [aspect skill](../agent/deep_agent/skills/remotion-aspect-ratio-variants/SKILL.md)
for approved flat-master or existing Remotion-timeline aspect changes. The same matrix tool
accepts `brief.reframe_only=true` and minimal rows. `crop_plan_preview` is pure geometry;
`detect_scenes` supplies bounded cut times, and fixed crop/pad operations preserve real
file provenance. Per-shot timeline windows are static, validated in display coordinates
and switch to whole-frame blurred padding if a supplied box cannot fit its safe zone.
No detector runs. Local crop/pad timeline fields share their canonical contract with the
Lambda validator, which explicitly refuses them before any AWS call. Existing deployed
Lambda timelines remain unchanged. Render results are editorial candidates with contact
sheets and pending review, not certified delivery output. Paid outpainting still selects
`edit-v2v` and pauses with the existing cost estimate. No model defaults or spend caps change.

## Local delivery validation

The editor role discovers `Remotion___deliver_render` (`delivery_render`) and
`Remotion___qc_deliverable` (`deliverable_qc`). The executor runs them in process on the
host owning the authenticated job directory. They are free, bypass the generic Remotion
Lambda estimate, and require no spending approval. Approval-exempt sets and spend caps
are unchanged. Unscoped direct invocation and Lambda execution are refused.

Delivery stages a finished file or matrix manifest, uses fixed finishing operations,
normalizes audio to the preset target, writes versioned names and hashes, and QC checks
the actual result. The completion guard binds the report to current files, rejects stale
or incomplete checks, and prevents a previous successful render from overriding current
failed QC, including turn-limit recovery. Failure summaries preserve worker reasons
verbatim. Existing ordinary assembly validation remains compatible.

The three guides add delivery, loudness and deliverable QC routing. The 352 retained rows
now contain 346 active cases and 6 skips. RT-E043 awaits exact OCR verification; the other
five are provider dependencies, including RT-176's pending capture. `project.confidential` never changes these routes.
See [contracts and operator commands](REMOTION_EDITING.md). Offline real-binary verification
is supporting evidence; Comet Studio E2E is blocked by unavailable browser control here.

## Named-only fal video

Explicit Pixelcut looping video and PixVerse VibeMV requests route through `named-provider`
and the existing media role. `Fal___pixelcut_looping_video` and `Fal___pixverse_vibemv`
reuse `Fal___get_video_task`, shared fal credentials and dry-run guard. They are never
defaults or exceptions; unnamed executor calls and direct Studio invokes are blocked.
Both always interrupt with cost even in autonomous mode and with premium approval disabled.
Measured VibeMV source duration stays local; consent flags never enter the provider payload.
Inventory is 21 providers, 140 tools, 44 skills, 346 active fixtures and 6 dependency skips.
See [named fal video](providers/named-fal-video.md) for contracts, dated official prices,
commercial hosted terms and training exclusion. Comet E2E remains blocked here.

## Motion carry quality gate

The editor discovers `Remotion___motion_carry_probe` as an owned-job local tool.
Its canonical ID is `motion_carry_probe`. It takes `job_id`, in-job MP4
`input_path` and optional exact `timeline`, with no cost approval or provider
call. The installed Deep Agents 0.7.23 dispatcher and interrupt predicates stay
unchanged. `MOTION_CARRY_QC_DRY_RUN=true` is the default.

Motion graphics, product demos, knowledge explainers and explicit HyperFrames
films require a saved passing report that matches the current artifact checksum
before completion. The shared completion validator also covers run-limit
recovery. A failure is quoted verbatim with timestamped fixes and an offered
re-render through Remotion, or HyperFrames only if explicitly requested.
Dry-run/skipped measurements are incomplete QC and preserve the existing render.
Generative continuity remains `local_qc`. All thresholds are PROVISIONAL.
Current inventory is 21 providers, 140 tools, 44 skills, 352 routing rows with
346 active and six dependency skips. See [motion carry QC](MOTION_CARRY_QC.md).

## Cinematic product launch planning

The manager and editor read
[cinematic product promo](../agent/deep_agent/skills/cinematic-product-promo/SKILL.md)
for cinematic product reveals and beat-synced launch films. Its optional
[launch motion cards](../agent/deep_agent/skills/cinematic-product-promo/references/launch-motion-techniques.md)
add one-shape continuity, spring settling and cursor-driven reveals as planning guidance.
Technique IDs stay outside strict storyboard/render arguments. Full realization needs
supplied pre-rendered shots; the existing timeline cannot execute custom morphs, springs
or cursor events. Product-film technique requests select this skill and keep the existing
renderer and approvals. Generic website motion retains its previous route. The editor discovers
`ShotRecipes___shot_recipe_search`, a local data tool with no media-job directory,
network, model or keys. Its free search mode selects cards; its validation mode checks
storyboard timing and returns native timeline arguments plus separate stem plans.
`ShotRecipes` belongs to `call_editor_tool`. Approval and cost rules for rendering,
voiceover and music remain unchanged. Every project uses the same capability map.

The route proposes recipe search before assembly. Named IDs and clear aliases remain
binding for the requested beat. The runtime cannot infer actual animation from a card
or execute imported reference paths. Unsupported custom shots require pre-rendered
user assets. Missing measured music beats, stem artifacts or capture footage remain
concrete blockers. `cutaway_record` stays provider pending.

SFX assets need Mixkit terms review before use. Cue categories alone do not license audio.
Use user-supplied assets with usable rights or disclose an empty SFX stem. Delivery still
requires loudness verification, actual playback, saved passing QC and matching output
checksums. The cinematic skill joins the existing motion-carry completion gate.

RT-174 and RT-175 are active. RT-176 remains skipped because capture is unbuilt, with an
active negative check of its skill and forbidden search tool. Four fixture negatives
protect the existing workflows. Current inventory is 21 providers, 140 tools, 44 skills,
352 routing rows, 346 active and 6 skipped. Docker's existing `COPY providers` and the
Gateway deployment ZIP's recursive provider copy include all cards and index data;
CI checks that the ZIP contains exactly 157 cards. Browser validation through Comet
is blocked here. See [cinematic product promo](CINEMATIC_PRODUCT_PROMO.md).

## Footage memory

The editor role discovers and calls five `FootageMemory___` tools for existing-footage
retrieval. The [skill](../agent/deep_agent/skills/footage-memory/SKILL.md) and deterministic
router share the measured-duration/reuse rule. An unknown duration checks status first.
Short single questions watch directly, repeated questions or long/folder footage build,
and current memory always wins over a new full watch. Query, narrow verification and
extraction are sequential execution groups. Every candidate cut needs a verified hit.
Transcript filler/pause cuts stay on conversational-edit and continuity stays on local_qc.

Build defaults to estimate; host approval is bound to the source hashes, immutable versions
and current plan settings. Long builds pause even in autonomous runs. Mock verification
cannot clear verify-before-extract. The existing spend cap and approval exemptions remain.
`FOOTAGE_MEMORY_DRY_RUN=true` and `FOOTAGE_MEMORY_BACKEND=gemini` are independent settings;
the default backend is a mocked candidate, not a promoted VLM. The disabled alternative
never reads a key. `allow_third_party_vlm` defaults false for the blocked future live path.

The [shared video index](VIDEO_INDEX.md) stores one DB per scoped project and ships its SQL
migrations with provider data. It records events now and reserves segment-edit DDL without
populating or wiring that feature. The offline A/B harness reports two-second timestamp
precision/recall from synthetic fixtures and cannot promote a default. No new secret is
required. See [Footage memory](FOOTAGE_MEMORY.md) and [decisions](footage-memory-decisions.tsv)
for configured unknown estimates, licences, blocked live paths and the workbook reconciliation.

Inventory is 21 providers, 140 tools, 44 packaged skills, and 352 routing rows, with 346
active and six unchanged skips. Comet E2E is blocked in this environment.

## Chat-story routing and rendering

The [chat-story skill](../agent/deep_agent/skills/chat-story-video/SKILL.md) creates fictional
conversation shorts from a bounded messages table. The deterministic router proposes
`remotion_render` through `call_editor_tool`, including CSV batches. It does not propose
a video model for the thread. The shared `request_tool_blocker` filters generative video
from discovery and refuses attempted thread generation before dispatch.
Unrelated mentions and approved quoted copy retain their previous route.

One script uses `Remotion___render_timeline` with `chat_story`. Batches use the existing
`Remotion___render_ad_variants` with `brief.mode="chat_story"`, per-row payloads and an empty
master asset. Planning is free. First and batch renders still use the native Deep Agents
interrupt and the host's trusted `plan_hash` authorization, including in autonomous mode.
No new approval arguments, dispatch wrappers, provider or Gateway tool are added.
The existing spending cap and approval exemptions stay unchanged.

The skill declares the configured `chat_story` feature. The local worker can render it;
the Lambda backend returns an explicit unsupported-composition refusal until deployed and
verified. Messages stay verbatim, contacts are fictional and avatars are initials or
placeholders. Generic is the enabled theme. A disabled lookalike request discloses generic
fallback. Final delivery requires loudness and deliverable QC reports that still match
the output checksums. First-render playback and still inspection require visual review.

RT-180 and RT-181 plus six routing negatives remain active alongside the podcast cases.
The combined fixture has 352 rows, with 346 active and six unchanged skips. The skill inventory is 44. The provider and tool inventories
are 21 and 140. `docs/CHAT_STORY_VIDEO.md` describes the payload, timing and batch
contract. Comet E2E and live Lambda chat rendering remain unverified here.

## Podcast audiogram routing and approval

`podcast-audiogram` adds an existing-recording waveform/caption workflow. Its deterministic
route plans `elevenlabs_stt` then `remotion_render` when word timings are missing. Supplied
word timings, exact-source indexed words or SRT omit paid transcription. The draft's
`transcribe_audio` name is a placeholder; the real tool is
`ElevenLabs___speech_to_text_convert`, dispatched by the audio role. Saved transcript IDs
use `ElevenLabs___speech_to_text_transcripts_get`; phrase index events are not invented word
alignment. Caption source text remains data rather than an instruction or provider selector.

The shared executor requires approval for speech-to-text and forced alignment, including
autonomous calls. Existing spend caps and approval exemptions remain unchanged. The route
keeps the source voice: replacement speech, cloning and lip-sync are blocked by the shared
request guard. A long-episode best-moment pull starts with footage-memory; showing a
captioned talking head remains conversational-edit. Channel stings and YouTube end screens
route to motion-graphics, while lower thirds and ad variants retain their owners.

The editor discovers the existing timeline tool's `template` argument and the ffmpeg
`audio_envelope` operation. Owned asset resolution includes source audio and template art.
Local rendering accepts the bounded canonical plan; Lambda refuses named templates until
`REMOTION_TEMPLATE_CONTRACT_VERSION=1` declares the separately deployed matching composition.
The skill gates extra aspects on first-render visual review and requires loudness/deliverable
QC for every output. No new dispatch wrapper, target, paid provider, secret or training grant
is introduced. Inventory is 44 skills, 352 fixture rows, 346 active and six unchanged skips.
See [podcast audiograms](PODCAST_AUDIOGRAM.md) for exact contracts and UNVERIFIED limits.

## Descriptive art catalog

The existing art-style-motion skill selects from 141 neutral treatments, imported as
text from 98 specialized prompts and 43 general guides. All 141 entries have recorded
prompt or direction adaptations. No identical prompts or source style names overlap
between the sets; related media remain distinct treatments. Safe selection is returned
through `read_studio_context.style_catalog`, using a pure deterministic helper and no
new tools. Verbatim source and the scan report are internal provenance outside the
agent skill filesystem. User-named existing cards retain precedence and descriptive
labels. Browse requests do not generate assets.

The MIT notice is retained. No source demo assets or tooling are included. Named-film
associations can create IP risk; prompts describe materials and motion only. All existing
model, licence, training, price, approval, and dry-run policies remain unchanged. The
renderer still requires authored assets for unsupported procedural motion.

Inventory is 21 providers, 140 Gateway tools, 44 skills, 141 catalog treatments, and
352 fixture rows, with 346 active and six skipped. RT-160 through RT-162 stay unchanged.
RT-CAT-001 through RT-CAT-012 are active. No provider-pending row is falsely activated.
Comet E2E is blocked. See [art-style motion](ART_STYLE_MOTION.md) and
[decisions](art-style-catalog-decisions.tsv) for counts, provenance, and limits.

## Local UI animation

`lottie-animation` uses the editor's existing dispatch wrapper for three local tools.
The worker validates typed scene or supplied JSON arguments, confines files to the
current Studio job and saves JSON plus a deterministic dotLottie container. The
registry, local discovery, free-tool list and approval exemptions agree. A cross-job
request is rejected before filesystem access. The direct Studio invoke endpoint
requires chat so it cannot bypass current-job ownership.

The agent writes the scene; the tools make no model or network call and need no new
secret or dry-run switch. Existing paid approval rules and autonomous spending caps
are unchanged. Preview MP4 and GIF files support review of the vector deliverable;
they do not require a final Remotion video. Unsupported preview features are reported
as `not_previewed`, with incomplete validation kept explicit. Target-player visual
review is distinct from structural compatibility checks.

The installed `deepagents==0.7.23` signatures were inspected. The feature uses the
existing skills backend, editor role and conditional `interrupt_on` policy; it adds
no custom planning, filesystem or interrupt mechanism. See
[Lottie tools](LOTTIE_ANIMATION.md) and the
[decision trail](lottie-animation-decisions.tsv).

Inventory is 21 providers, 140 Gateway tools, 44 skills and 352 fixture rows, with
346 active and six dependency skips. The runtime image installs FFmpeg for local
preview encoding and includes the in-house Python implementation and MIT notice.


For Lottie inputs, the existing owned Studio asset resolver can stage an attached SVG
handle into the trusted current job before provider validation and execution. The
provider sees a confined path, and the event retains the owned source version ID.
Unknown or unauthorized assets refuse without fallback to arbitrary host paths.

## Local logo geometry approval

The editor role admits `Logo___logo_vectorize`. Native Deep Agents approval applies only
to its `approve` operation and always pauses, including autonomous runs. All operations
are free. The approval description asks for review of the exact SVG, overlay, smoothness
audit and mark rights. The executor supplies an approval context only after the human
resumes the existing interrupt. The model cannot grant approval in tool arguments.
Rejection performs no approval write. A worker restart requires vector reapproval.

Local discovery overrides any remote tool with the same name. Catalog `local_only=true`
prevents deployment to Gateway Lambda, and Lambda separately refuses direct invocation.
Every Logo call and the `logo-animation` render template must match the trusted Studio
job. The template requires local rendering so private source geometry stays on the worker.
No new secret or spending exemption is introduced.

The `logo-animation` skill keeps vector preparation and rendering in sequential execution
groups across the exact-checksum approval. Studio completion requires a saved passing logo
QA report bound to the MP4, approved SVG and motion specification. The report includes
final-frame, decoded-motion, continuity and easing checks. Existing deliverable QC must
certify that same final MP4, and later render or finishing work invalidates earlier QA.
Failures replace premature completion copy verbatim. The skill requests user rights
confirmation and leaves customer visual review explicit. See [contracts and limits](LOGO_ANIMATION.md).

RT-184 is active with the canonical `logo_vectorize then remotion_render` sequence.
Eight added cases protect supplied-logo variants and the existing motion, vector-design
and podcast routes. Inventory is 21 providers, 140 tools, 44 skills, 352 fixture rows,
346 active and six dependency skips. Comet browser verification remains incomplete until
the required Studio flow has been exercised.

## Seedance prompt diagnosis

The router exposes `intent_route.prompt_diagnosis` for explicit Seedance failure reports
or prompt-repair requests. Its immutable helper returns a key, neutral suggestion and
rewrite guidance. These t2v routes contain no tool, alias, dispatch wrapper or media steps.
The existing request blocker excludes paid media dispatch while leaving free saved-job
polling available. A new explicit generation turn uses the normal fresh native approval
and cost estimate. No approval exemption, parallel resume or spending rule changes.

The on-demand [t2v reference](../agent/deep_agent/skills/t2v/references/seedance-prompts.md)
and adjacent MIT notice are included in package data. Language, voice and camera directions
stay inside the existing prompt field. The adapted French web-interface guidance is
UNVERIFIED against the API until a live A/B. See [integration details](SEEDANCE_2_5.md#prompt-writing-and-failure-diagnosis).
Current inventory is 21 providers, 140 tools, 44 skills and 352 fixture rows, with 346 active
and six skipped. Comet browser validation is blocked by unavailable control; live calls
are prohibited for this branch.

## Measured reference analysis

The editor role exposes local-only `Reference___shot_breakdown` for the
[reference-shot-breakdown skill](../agent/deep_agent/skills/reference-shot-breakdown/SKILL.md).
The media role exposes the separate `Gemini___judge_shots` rubric on the existing
judge transport. `Gemini___get_task` keeps the continuity default and accepts
`rubric="reference_shots"` with measured IDs for shot labels. Native approval, checkpoint
and spending controls remain in the installed Deep Agents 0.7.23 harness. No custom graph
is added. See [the analysis contract](REFERENCE_SHOT_BREAKDOWN.md) for integrity and review limits.

## Episodic fiction planning and production

The [short drama workflow](SHORT_DRAMA_SERIES.md) adds free `review_drama_outline` and
`validate_drama_episode` tools to the manager and roles. Outline approval uses the existing
Deep Agents 0.7.23 native interrupt/checkpointer/resume path. Its rejection stays local.
The host-owned `drama_series` session snapshot stores the approved outline hash, validated
episode, exact production jobs, continuity registry and submitted job IDs. Virtual files
remain agent-editable project records and cannot prove approval.

Role dispatch refuses unplanned or changed paid arguments. Every paid job in an active
series requires cost approval, including autonomous images and audio. This leaves global
approval exemptions and spending caps intact. Per-shot selection retains user-named models
and real-person flags while applying dialogue and duration constraints from the shot.
An explicit request to stop the series disables its gate without discarding its records.
No provider, paid Gateway tool or model default is added. RT-188 is active; Comet browser
validation and actual artifact playback are pending under the offline-only task constraint.

## Codebase video

The codebase-video route selects local assembly before generic video or narration
routing. Its boundary guard excludes generated code cards and refuses a cloud
render backend at both discovery and dispatch. Explicit HTML renderer requests
preserve the existing incomplete preview rather than silently switching renderers.

The skill uses the installed Deep Agents 0.7.23 `task` tool with the existing
planner role for fresh claim review. The planner receives the exact source snapshot
and claim ledger paths and has no paid media dispatch tool. Existing role skills,
checkpointer, thread IDs, approval interrupts and spend caps remain unchanged.
The ledger is an editorial instruction contract, not a new host-enforced validator.
Studio cannot inspect an arbitrary checkout or typeset a code card by itself.
Unavailable source access, literal card assets or independent review leave production
blocked. See [codebase video](CODEBASE_VIDEO.md) for the supported boundary.

Inventory is 21 providers, 140 Gateway tools, 44 skills and 352 routing rows,
with 346 active and six existing dependency skips. No model configuration changes.

## Non-fiction series planning

The [series planner](SERIES_VIDEO_PLANNER.md) uses the installed Deep Agents 0.7.23
skill loader, planner and checkpointed file tools. It proposes no Gateway tool.
The planning turn saves a draft episode graph, shared locks and briefs and returns
them for review in chat. This review is distinct from the fictional drama native
outline gate and grants no spend. After approval, a requested episode uses an existing
explainer skill with its normal cost approval and production checks.
The shared request blocker refuses Gateway media work during a planning turn;
schema search stays available. Later single-episode requests preserve their existing route.

RT-189/190 add two planning cases without changing the six existing skips. Inventory
is 21 providers, 140 Gateway tools, 44 skills, 352 routing rows and 346 active rows.
Comet browser validation is pending because browser control is unavailable and live
API calls are prohibited.


## Finishing preview review

The upscale skill uses native `prepare_finishing_preview` and `review_finishing_preview`
with the existing Topaz Gateway tools. The host clips an owned source to at most three
seconds, then requests the ordinary paid-preview approval. Only a saved, measured processed
artifact can reach the native visual-review interrupt. Studio displays linked original and
enhanced playback, scrubbing, and side-by-side or A/B views.

Accepting the comparison permits the exact source and settings to reach a separate full-job
cost approval. Rejecting it blocks that full request. Source, sample, or artifact checksum
changes invalidate review. A sample that covers the entire source can finish after approval
without another paid request. Dry-run responses and partial samples never complete a full
source request. See [Topaz preview review](TOPAZ_PREVIEW_COMPARE.md) for the contract and
validation limits.

This adds two native agent tools, no provider or Gateway endpoint. Current inventory is
21 registered providers, 140 Gateway tools, 44 skills, and 353 routing rows. There are
347 active routes and six unchanged skips. RT-194 is a new radar workflow route.
