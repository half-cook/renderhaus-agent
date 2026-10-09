# Studio Deep Agents backend

Renderhaus uses `deepagents==0.7.23` by default. One chat handles planning, media generation,
refinement, and final Remotion assembly. Canvas references are optional. The existing Studio
request, job, approval, progress, asset, and conversation contracts remain in place.

## Configuration

| Variable | Behavior |
| --- | --- |
| `RENDERHAUS_AGENT_BACKEND` | `deepagents` by default; `codex` selects the retained app-server backend. Other values fail explicitly. |
| `RENDERHAUS_AGENT_MODEL` | LangChain `provider:model`, such as `openai:gpt-5.6-luna`, `anthropic:claude-sonnet-4-6`, or `bedrock_converse:<model-id>`. |
| `AGENT_MODEL` | Fallback when the new model variable is absent. Unqualified names and `openai/` names select OpenAI. Codex still uses this variable. |
| `RENDERHAUS_AGENT_TIMEOUT_SECONDS` | Graph execution deadline, default 1800 seconds. |
| `STUDIO_MEDIA_WAIT_SECONDS` | Host polling deadline per provider job, default 600 seconds. |
| Provider `*_DRY_RUN` variables | Keep their existing provider behavior. The agent cannot change configuration. Dry runs never satisfy video delivery. |

The default model remains `openai:gpt-5.6-luna`. OpenAI uses `OPENAI_API_KEY`; Anthropic uses
`ANTHROPIC_API_KEY`. Bedrock uses the deployment's IAM credential chain and configured AWS
region. No keys appear in source or prompts. Studio readiness checks the selected provider;
Bedrock readiness does not probe AWS and is not proof that credentials or model access work.
The backend and model configuration must agree between the Studio server and AgentCore worker.

## Reasoning and tool execution

`agent/studio_agent_next.py` owns public Pydantic contracts, Studio context, Gateway billing,
asset handles, output validation, and the AgentCore SSE entrypoint. `run_studio_agent()` selects
the backend. An explicitly injected Codex harness selects Codex for existing callers and tests.
`agent/deep_agent/runner.py` compiles `create_deep_agent` with the configured model, native
skills, role-specific subagents, memory, virtual files, checkpointer, and HITL middleware.
`ToolStrategy(StudioAgentOutput)` enforces the existing downloadable Markdown result schema.

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

## Provider ladder

The config capability table filters required features before quality tier and cost. Finished
shots default to Standard. Draft previews and rejected-shot retries use Wan; confidential
projects stay Wan. The shared executor discloses the provider/model and estimated cost in
chat, retains existing approval/spend rules, and logs provider outcomes locally with Wan-only
training eligibility. See [capabilities, tiers, project policy and outcomes](SKILLS.md#provider-capability-table-and-ladder).

## Skills and delegation

Fifteen packaged `SKILL.md` files live under `agent/deep_agent/skills/`.
Deep Agents reads their metadata first. Full instructions enter context only when a relevant
skill is read. `metadata.include_tools` discloses the corresponding dispatch tools.

| Skill | Workflow |
| --- | --- |
| `video-short` | Brief, inexpensive still preview, Standard clips from the provider ladder, audio if needed, Remotion export. |
| `product-images` | Seedream generation or reference-based editing, one still before additional variants. |
| `storyboard-shots` | Shot plan, consistent Seedream keyframes, approved stills into the selected Standard image-to-video route. |
| `audio` | ElevenLabs voiceover/music/SFX or Fish Audio speech if that target is available. |
| `final-assembly` | Existing asset handles into a typed Remotion timeline, saved identifiers, poll the final MP4. |
| `refinement` | Edit the referenced version and reuse unaffected media; prefer timeline edits for timing changes. |

Eight additional intent skills are `t2v`, `i2v`, `edit-v2v`, `still-then-video`, `audio-bed`,
`motion-graphics`, `continuity-qc`, and `resolve-handoff`. The six original names remain.
Their wrapper and exact Gateway tool mappings are listed in [Skills and routing](SKILLS.md).
The deterministic policy router proposes the selected skill and tool in the graph input and
Studio context. Unsupported providers and local Resolve workflows remain explicit pending
routes. The fixture retains 58 rows, with 23 active and 35 explicit skips, including
the three new HyperFrames cases and all original workbook rows.

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
policy schema, cached/lazy SigLIP and DINOv2 QC, unconfigured face interface, DINOv3 gating,
and all pending-provider drafts.

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

Native `interrupt_on` uses a `when` predicate. Non-autonomous provider dispatch pauses;
autonomous standard media runs proceed under the existing spending authorization.
Kling and Runway premium video calls now interrupt autonomous runs by default. The shared
policy adds an estimate from `server.billing_rates.cost_for` to approval descriptions and
visible labels; unconfirmed prices remain unknown. `RENDERHAUS_PREMIUM_VIDEO_APPROVAL=false`
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
It installs pinned dependencies and verifies the Deep Agents version and all fifteen packaged
skills during the build. The entrypoint remains `python -m agent.studio_agent_next`.
No Studio UI or database schema change is required.

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

Comet browser E2E is blocked in this environment. There is no controllable browser, Clerk
session, or paid provider credential set. The blocker is recorded under ignored
`.renderhaus/e2e/` using `scripts/browser_e2e_hook.py`. No live E2E pass is claimed.
