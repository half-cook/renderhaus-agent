# Studio Deep Agents backend

Renderhaus uses `deepagents==0.7.23` by default. One chat handles planning, media generation,
refinement, and final Remotion assembly. Canvas references are optional. The existing Studio
request, job, approval, progress, asset, and conversation contracts remain in place.

## Configuration

| Variable | Behavior |
| --- | --- |
| `RENDERHAUS_AGENT_BACKEND` | `deepagents` by default; `codex` selects the retained app-server backend. Other values fail explicitly. |
| `RENDERHAUS_AGENT_MODEL` | LangChain `provider:model`, default `anthropic:claude-haiku-5-5`. Supported prefixes are `anthropic`, `openai`, `bedrock`, and `bedrock_converse`. Unknown prefixes and empty model IDs fail explicitly. |
| `RENDERHAUS_AGENT_EFFORT` | Anthropic effort, default `medium` for manager/planner/general-purpose and `low` for media/audio/editor. Accepts `low`, `medium`, `high`, `xhigh`, or `max`; maps to `output_config.effort`. Ignored for OpenAI, Bedrock, Codex, and injected test models. |
| `RENDERHAUS_AGENT_MODEL_<ROLE>` | Optional override for `PLANNER`, `MEDIA`, `AUDIO`, `EDITOR`, or `GENERAL_PURPOSE`; falls back to the global model. |
| `RENDERHAUS_AGENT_EFFORT_<ROLE>` | Optional matching effort override; falls back to the global effort, then the role default. |
| `AGENT_MODEL` | Explicit legacy fallback when the new model variable is absent or blank. Unqualified names and `openai/` names select OpenAI. Codex still uses this variable and defaults to `gpt-5.6-luna`. |
| `RENDERHAUS_AGENT_TIMEOUT_SECONDS` | Graph execution deadline, default 1800 seconds. |
| `STUDIO_MEDIA_WAIT_SECONDS` | Host polling deadline per provider job, default 600 seconds. |
| Provider `*_DRY_RUN` variables | Keep their existing provider behavior. The agent cannot change configuration. Dry runs never satisfy video delivery. |

Satya chose Claude Haiku 5.5 for the manager and every subagent. Manager, planner and
research roles use medium effort for decisions across multiple steps. Media, audio and editor
roles use low effort for focused dispatch. Set a role override such as
`RENDERHAUS_AGENT_MODEL_PLANNER=anthropic:claude-opus-5-5` to change the planner independently.
Set `RENDERHAUS_AGENT_MODEL=anthropic:claude-sonnet-5-5` to change the manager and inherited
role models. The global effort overrides every role default unless that role has its own setting. Set
`RENDERHAUS_AGENT_MODEL=openai:gpt-5.6-luna` to select the previous default. Selection reads the
first nonblank value of `RENDERHAUS_AGENT_MODEL`, then `AGENT_MODEL`, then the Haiku default.
Studio no longer injects a legacy `AGENT_MODEL` value that would mask this default.

Anthropic uses `ANTHROPIC_API_KEY`; OpenAI uses `OPENAI_API_KEY`. A missing selected-provider
key prevents model construction with an error naming the required environment variable.
Importing configuration and injecting a fake chat model require no keys. Provider media
dry-run flags do not make a real planning-model invocation free or offline. Bedrock uses the
deployment's IAM credential chain and configured AWS region. Studio readiness checks the
selected provider; Bedrock readiness does not probe AWS or prove model access. The Studio
server and AgentCore worker must use matching backend, model, and effort configuration.

### Verified model contract and pricing

Anthropic's [Haiku 5.5 overview](https://platform.claude.com/docs/en/models/haiku-5-5/overview)
and [migration guide](https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide),
read 2026-10-09, verify `claude-haiku-5-5`, adaptive thinking, effort (default medium),
and the 1M context window. Fixed thinking budgets and assistant prefill are rejected.
The integration omits temperature, top_p and top_k for every Anthropic model. Adaptive thinking
and effort are sent only to models in the supported adaptive allowlist; older overrides keep
native parameters. Haiku accepts forced tools but omits thinking on that response. Automatic
tool choice retains thinking and also permits Opus/Sonnet 5.5 overrides.

First-party list prices per million tokens come from Anthropic's
[official pricing page](https://platform.claude.com/docs/en/about-claude/pricing), read 2026-10-09.

| Model / prompt length | Input | Output | 5m cache write | Cache read |
| --- | --- | --- | --- | --- |
| Haiku 5.5, <=100k | $0.10 | $0.50 | $0.125 | $0.01 |
| Haiku 5.5, >100k | $0.50 | $2.50 | $0.625 | $0.05 |
| Opus 5.5 | $4.00 | $20.00 | $5.00 | $0.20 |
| Sonnet 5.5 | $2.00 | $10.00 | $2.50 | $0.10 |

Haiku's threshold counts uncached input, cache reads and cache writes for each call, rather
than the aggregate turn total. Thinking tokens are already included in output usage.
`agent.deep_agent.usage` emits `agent_model_usage` JSON records with the run scope, model,
call count, token totals, estimated list cost and unknown-cost call count, including subagents
and approval resumes. It records completed messages once by message ID. These estimates use
5-minute writes and first-party rates; partner hosts, discounts, taxes and 1-hour caches require
separate pricing. Unknown models have no invented rate. No live model invocation was performed.

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

Demoted generation/edit/image providers remain built and explicit-only through named-provider.
Vidu's archived skill is removed while its Fal tools remain. All paid video pauses with an
estimate even during autonomous runs when the global video-approval switch is enabled.
Only the existing legacy Wan provenance/training retry path retains its special behavior.
See [the capability map](CAPABILITY_MAP.md) and [routing policy](SKILLS.md#capability-selection).

## Skills and delegation

There are 24 packaged `SKILL.md` files under `agent/deep_agent/skills/`.
Deep Agents reads metadata first. Full instructions enter context when a relevant skill is read.
`metadata.include_tools` documents real dispatch wrappers, which are stably bound per role. `metadata.routing_tools` holds
canonical capability/workflow IDs, while `metadata.gateway_tools` lists built names only.
Pending aliases cannot dispatch as Gateway tools. The generated inventory is in
[packaged skills](SKILLS.md#packaged-skills).

The original video-short, product-images, storyboard-shots, audio, final-assembly and refinement
skills remain. Image-gen applies GPT still defaults and Recraft/Ideogram exceptions.
Named-provider honors explicit demoted providers. Pending specialists include
act-two and Kling Motion Control. Mureka lyrics-video and Topaz finishing are built. Product-demo-video keeps the pending cutaway capture utility;
whiteboard-explainer plans Remotion templates without claiming unsupported marker-hand animation.

The deterministic router supplies skill and tool proposals in graph input and Studio context.
The capability-map fixture contains 129 retained rows, with 106 active and 23 dependency skips.
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

`call_media_tool` dispatches the `ModelStudio` target. The edit-v2v and refinement skills
discover its real Gateway names. `wan3_edit` and `wan3_extend` are built capability defaults
with declared Seedance 2.5 edit/extend interims while the Wan model commercial policy is
blocked. Explicit Luma, Aleph, and VACE remain available.

Paid edit/extend interrupts retain the installed deepagents 0.7.23 checkpointer and
`Command(resume=...)` behavior. Cost descriptions use regional input plus output seconds,
including existing platform fees. Approval/rejection recovery is tested in autonomous runs.
The free poll tool uses the existing job loop at 15-second intervals and persists output.
Training eligibility is false under proprietary service terms.

The default legacy US base URL remains UNVERIFIED for generation and blocked live.
Preview licensing also blocks customer live use on workspace hosts. Configuration,
smart-duration limits, the licence restriction, and blocked Comet E2E are documented
in [the Model Studio provider reference](ALIBABA_MODELSTUDIO.md).

## Seedance 2.5 dialogue and edit interims

The Seedance target remains in `DISPATCH_TARGETS.call_media_tool`. Its five generation tools
use the existing callable `interrupt_on` cost descriptions and checkpointer/resume protocol in
installed deepagents 0.7.23. No manager or subagent model changes are part of this upgrade.
The host defaults to fal US and reuses fal polling; saved endpoint provenance survives a
transport configuration change. All Seedance outputs are ineligible for continuity training.

Synthetic dialogue uses the Seedance 2.5 exception for t2v/i2v/reference video. Real-person
references force Wan generation with consent and refuse the Seedance edit/extend interim.
Changing Wan's `live_enabled` policy flag restores default selection; the unchanged hard
Model Studio adapter restriction still blocks commercial live work. See
[Seedance contracts, pricing and unresolved limits](SEEDANCE_2_5.md).

## OpenAI still images

`OpenAI___generate_image` and `OpenAI___edit_image` implement the still-image and image-edit
defaults, including text-in-image generation. Edits accept a primary image, up to 15 additional
references, and an optional mask. Results contain saved images synchronously, without polling.
Seedream remains explicit-only. Spending approval and visual approval remain separate.
The OpenAI branch activated eight GPT routing rows. With Sync, 98 routing cases are active
and 31 remain skipped, including Recraft and Ideogram specialists.
There are 12 providers, 95 Gateway tools, and 24 packaged skills.

[OpenAI configuration and verified sources](OPENAI_IMAGES.md) describe the default dry-run flag,
unknown pre-call costs, output training restriction, and blocked Comet validation.

## Sync dispatch and approval

`Sync` is a media-role dispatch target. The converted lipsync skill exposes the media and
audio wrappers for the ElevenLabs TTS → existing-footage sync-3 chain. Manager and subagent
models remain `claude-haiku-5-5`. The installed deepagents 0.7.23 signatures govern native
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
Inventory is 12 providers, 95 Gateway tools and 24 skills. See [HeyGen](HEYGEN.md).

Mureka music and lyrics-video share the audio role and six Gateway tools. Native
0.7.23 interrupts quote paid video and resume once after approval; rejection performs
no dispatch. This includes autonomous lyrics-video requests. Songs pause unless
autonomous. See [Mureka](MUREKA.md) for transport, pending raw-audio preparation,
licences and blocked browser validation. The current inventory is 14 providers,
105 Gateway tools and 24 skills.
