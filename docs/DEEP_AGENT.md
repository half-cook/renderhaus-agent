# Studio Deep Agents backend

Renderhaus uses `deepagents==0.7.23` by default. One chat handles planning, media generation,
refinement, and final Remotion assembly. Canvas references are optional. The existing Studio
request, job, approval, progress, asset, and conversation contracts remain in place.

## Configuration

| Variable | Behavior |
| --- | --- |
| `RENDERHAUS_AGENT_BACKEND` | `deepagents` by default; `codex` selects the retained app-server backend. Other values fail explicitly. |
| `RENDERHAUS_AGENT_MODEL` | LangChain `provider:model`, default `anthropic:claude-opus-5-5`. Supported prefixes are `anthropic`, `openai`, `bedrock`, and `bedrock_converse`. Unknown prefixes and empty model IDs fail explicitly. |
| `RENDERHAUS_AGENT_EFFORT` | Anthropic effort, default `high`. Accepts `low`, `medium`, `high`, `xhigh`, or `max`; maps to `output_config.effort`. Ignored for OpenAI, Bedrock, Codex, and injected test models. |
| `AGENT_MODEL` | Explicit legacy fallback when the new model variable is absent or blank. Unqualified names and `openai/` names select OpenAI. Codex still uses this variable and defaults to `gpt-5.6-luna`. |
| `RENDERHAUS_AGENT_TIMEOUT_SECONDS` | Graph execution deadline, default 1800 seconds. |
| `STUDIO_MEDIA_WAIT_SECONDS` | Host polling deadline per provider job, default 600 seconds. |
| Provider `*_DRY_RUN` variables | Keep their existing provider behavior. The agent cannot change configuration. Dry runs never satisfy video delivery. |

The planning default is Claude Opus 5.5 at high effort. Set
`RENDERHAUS_AGENT_MODEL=openai:gpt-5.6-luna` to select the previous default. Selection reads the
first nonblank value of `RENDERHAUS_AGENT_MODEL`, then `AGENT_MODEL`, then the Opus default.
Studio no longer injects a legacy `AGENT_MODEL` value that would mask this default.

Anthropic uses `ANTHROPIC_API_KEY`; OpenAI uses `OPENAI_API_KEY`. A missing selected-provider
key prevents model construction with an error naming the required environment variable.
Importing configuration and injecting a fake chat model require no keys. Provider media
dry-run flags do not make a real planning-model invocation free or offline. Bedrock uses the
deployment's IAM credential chain and configured AWS region. Studio readiness checks the
selected provider; Bedrock readiness does not probe AWS or prove model access. The Studio
server and AgentCore worker must use matching backend, model, and effort configuration.

### Verified model contract and pricing

Anthropic's [Opus 5.5 overview](https://platform.claude.com/docs/en/models/opus-5-5/overview)
and [models overview](https://platform.claude.com/docs/en/models/overview) list
`claude-opus-5-5`. The [effort reference](https://platform.claude.com/docs/en/build-with-claude/effort)
documents `output_config.effort` and all five supported levels. These sources were read
2026-10-08. The requested high setting overrides Anthropic's medium default for this model.

Base API pricing is **$4 per million input tokens and $20 per million output tokens**, from
Anthropic's [official pricing page](https://platform.claude.com/docs/en/about-claude/pricing),
read 2026-10-08. Thinking counts toward output usage. Cache writes, cache reads, batch,
and fast mode have separate rates; this configuration does not select fast mode or batch.
No creative Gateway billing rate is added for the planning model.

The capability-map choice uses the Arena Agent board as supporting evidence. That board
measures coding and tool sessions, so its ranking does not establish creative-planning quality.
The offline regression suite verifies the integration with fakes, not Opus judgment or latency.

Claude is a proprietary commercial API under the
[Anthropic Commercial Terms](https://www.anthropic.com/legal/commercial-terms), read 2026-10-08.
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
`RENDERHAUS_AGENT_MODEL`, and `RENDERHAUS_AGENT_EFFORT` when supplied. The deployment preflight
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
`ToolStrategy(StudioAgentOutput)` enforces the existing downloadable Markdown result schema.

The configured Anthropic model is constructed lazily with LangChain `init_chat_model` before
Gateway discovery. It receives `thinking={"type": "adaptive"}` and `output_config.effort`.
Other provider strings retain Deep Agents' native initialization, including OpenAI Responses
API defaults. `langchain-anthropic==1.7.5` is already a pinned project dependency.

Opus 5.5 rejects forced tool choice, as documented in the
[migration guide](https://platform.claude.com/docs/en/models/opus-5-5/migration-guide), read
2026-10-08. The installed Anthropic adapter drops `ToolStrategy`'s forced choice when adaptive
thinking is configured. The graph still validates `StudioAgentOutput`; a schema tool call is
model-selected rather than forced. Between-tool notes can arrive as thinking blocks and are
not displayed as customer text. Explicit `report_progress` calls remain the update path.

`GatewayExecutor` is shared by both backends. It validates the discovered MCP schema, reuses
completed call IDs, refuses replacement renders while a saved render is active, restores exact
bucket/output identifiers, polls a single accepted job, registers media, and publishes Studio
progress. `GatewayMCPServer` remains the only remote provider boundary. It resolves asset
handles, charges/refunds usage, and preserves the existing authenticated HTTPS MCP transport.

Deep Agents exposes `report_progress`, `read_studio_context`, `record_media_outcome`, and Gateway semantic search.
Reading a relevant skill discloses `call_media_tool`, `call_audio_tool`, or `call_editor_tool`.
These tools accept the exact discovered Gateway name and an argument object. Discovery returns
actual schemas, including tools hidden from the initial catalog behind semantic search. Unsupported or
undiscovered tools fail without dispatch. Discovery itself does not need a spending approval.

The installed `langchain-mcp-adapters==0.3.1` imports MCP 1's `mcp.server.fastmcp`. This project's
installed MCP 2.3.0 has no such module. The backend therefore builds LangChain tools around the
existing MCP client rather than downgrading MCP or bypassing Studio policy. Adapters can replace
this conversion when they support the project's MCP version.

## Capability routing

The quality-first capability map selects an explicit requested provider/model, then a named
exception, then the capability default. Pending defaults use only declared interims.
Cost estimates support disclosure and approvals, never tier or price ordering. Stored
`confidential` and `quality_tier` project fields do not affect selection or approvals.
The shared executor enforces the same choice on both backends, including approved resumes.

Demoted generation/edit/image providers remain built and explicit-only through named-provider.
Vidu's archived skill is removed while its Fal tools remain. All paid video pauses with an
estimate even during autonomous runs when the global video-approval switch is enabled.
Only the existing legacy Wan provenance/training retry path retains its special behavior.
See [the capability map](CAPABILITY_MAP.md) and [routing policy](SKILLS.md#capability-selection).

## Skills and delegation

There are 24 packaged `SKILL.md` files under `agent/deep_agent/skills/`.
Deep Agents reads metadata first. Full instructions enter context when a relevant skill is read.
`metadata.include_tools` discloses real dispatch wrappers. `metadata.routing_tools` holds
canonical capability/workflow IDs, while `metadata.gateway_tools` lists built names only.
Pending aliases cannot dispatch as Gateway tools. The generated inventory is in
[packaged skills](SKILLS.md#packaged-skills).

The original video-short, product-images, storyboard-shots, audio, final-assembly and refinement
skills remain. Image-gen applies GPT still defaults and Recraft/Ideogram exceptions.
Named-provider honors explicit demoted providers. Pending specialists include lipsync,
act-two, upscale and lyrics-video. Product-demo-video keeps the pending cutaway capture utility;
whiteboard-explainer plans Remotion templates without claiming unsupported marker-hand animation.

The deterministic router supplies skill and tool proposals in graph input and Studio context.
The capability-map fixture contains 122 retained rows, with 80 active and 42 dependency skips.
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

Fish Audio is not in the current active provider catalog. Its speech tool is usable only when
Gateway discovers an available Fish Audio target. Skills explicitly report unavailable tools.
The model cannot invent a target or call a provider directly.

The `planner` subagent has no provider dispatch. `media` can dispatch only Seedance/Seedream/Kling/Runway/Fal/Luma;
`audio` can dispatch only audio providers; `editor` can dispatch Remotion and the optional HyperFrames tool,
including `Remotion___export_nle_timeline` for the DaVinci Resolve handoff. That export is free and
only packages existing project media, so it is exempt from approval (`APPROVAL_EXEMPT_TOOLS` in
`agent/gateway_executor.py`); every paid tool still follows the native approval policy. The overridden
`general-purpose` subagent also has no provider dispatch. All roles share project files and
read-only Studio context. They inherit native approval policy and have no shell tool.
All five roles inherit the manager's selected model and effort. There are no per-role model
environment variables in this clone. Deep Agents' native role `model` field remains available
to declarative subagents; this change adds no override or cheaper role-model selection.
The pure `Remotion___prepare_conversational_edit` requires cut-plan approval even when
autonomous. Its estimate is zero and its preview preserves asset handles. The editor receives
word timestamps from the manager/audio role, which alone can dispatch paid transcription.

The manager and each role explicitly install `TodoListMiddleware`. The installed 0.7.23
graph does not add it automatically. Multi-shot and multi-step requests can track `write_todos`
state across turns, while child todo lists remain separate from the manager plan. Subagent
task results merge only changed files, preventing unchanged sibling snapshots from replacing
another role's edits. Concurrent intentional edits to the same file still need task ownership.

Packaged skill metadata reloads on each ordinary turn, so skill descriptions and
`metadata.include_tools` updates reach existing conversations. Approval resumes retain their
checkpointed state. Dispatch wrapper validation runs before the approval predicate; malformed
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
`ProjectMemory` reloads it on each invocation because the upstream memory middleware caches its
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

## AgentCore and verification

`Dockerfile.agentcore` defaults to Deep Agents and retains Codex for explicit fallback.
It installs pinned dependencies and verifies the Deep Agents version and all 24 packaged
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
