# Studio Codex harness

Renderhaus now runs its manager through **Codex app-server**. Codex owns the model loop,
reasoning, tool turns, structured output, and context compaction. The Python application
owns Gateway access, customer approvals, billing, asset registration, and Studio events.
The `openai-agents` dependency and its `Runner`, `RunState`, and compaction session are removed.

## Why this integration

OpenAI recommends app-server for products that need conversation history, approvals, and
streamed events. Its protocol uses JSON-RPC over stdio and models work as threads, turns,
and items. See the [official app-server guide](https://learn.chatgpt.com/docs/app-server).

The [official Python SDK](https://learn.chatgpt.com/docs/codex-sdk) ships a pinned native
runtime. We install `openai-codex==0.154.0` and obtain that binary through
`codex_cli_bin.bundled_codex_path()`. Studio speaks the documented stdio protocol directly:
it needs to service async dynamic-tool requests while also interrupting a turn for a durable
approval pause. It does not wrap Codex as a tool inside another Agents SDK loop.

Dynamic tools are an **experimental app-server API**. The adapter opts into
`experimentalApi`, and the runtime version is pinned. The installed binary's
`app-server generate-json-schema --experimental` output was checked during implementation.

## Request flow

1. Start a private app-server process and complete `initialize` / `initialized`.
2. Authenticate with the existing server-side `OPENAI_API_KEY` using `account/login/start`.
3. Create or restore a Codex thread with the Studio instructions and configured `AGENT_MODEL`.
4. Start a turn with the request, canvas references, and `StudioAgentOutput` JSON schema.
5. Handle `item/tool/call` requests in Python. Record tool results and expose model-authored
   commentary through the existing Studio progress events.
6. Validate the final artifact and retain the successful Remotion MP4 delivery check.
7. Close app-server, save its flushed native rollout, and delete the temporary runtime directory.

The model sees `report_progress`, Gateway semantic search, and `call_gateway_tool`.
The pinned runtime exposes these through its native `functions.exec` Code Mode tool;
the Code Mode host stays enabled. Its JavaScript isolate has no direct filesystem or
network access, and nested calls return through the app-server dynamic-tool callback.
Search returns the actual names and schemas. The dispatch callback accepts only currently
discovered tools and validates arguments against the discovered input schema. This keeps
progressive discovery while avoiding a changing set of thread-level dynamic tools mid-turn.

All provider calls still pass through `GatewayMCPServer.call_tool`: opaque asset handles are
resolved at the boundary, usage is charged, failed MCP calls are refunded, and generated
assets are registered for later calls. The generic MCP transport uses the MCP Python library,
independent of the model framework.

## Conversations and approvals

Studio's existing conversation storage contains a versioned `renderhaus_codex_session` item:
the thread ID, a relative native rollout location, the rollout contents, and discovered Gateway
tool definitions. The snapshot is bound to the workspace/project/conversation. It contains no
Codex auth files. A fresh worker restores the rollout under its private Codex home, then resumes
by thread ID. This uses native persisted history, including Codex compaction records, without
depending on the experimental cloud-only `thread/resume.history` field.

The local Studio checkpoints complete native JSONL records after tool replies and completed
items, then saves the fully flushed rollout even when a run errors. `agent_checkpoints` stores
the execution snapshot, while conversation storage holds the latest continuation. Raw native
history is never returned by the public execution endpoint; the UI receives `checkpoint_at`.
Durable asset mappings and provider render identifiers travel with the snapshot. Native
context compaction continues automatically, with a brief memory update in the Studio.

**Stop & save progress** interrupts local work, closes the current approval, and retains
completed assets. Provider jobs already submitted may still finish. **Resume saved progress**
creates a new execution in the same conversation, supplies the recent tool ledger, and checks
existing jobs before allowing replacement renders. It is continuation, not rollback of media
or billing. Earlier conversation turns remain visible after reload.

Existing completed Agents SDK transcripts are imported once as reference data via
`thread/inject_items`; subsequent requests use the native Codex history.

For a non-autonomous request, each external Gateway call pauses before dispatch. Studio saves
the exact tool name, arguments, call ID, and job scope, tells Codex the call was not run,
interrupts the turn, and returns the existing `awaiting_approval` response. On approval,
Studio executes that saved call and continues the same Codex thread in a new turn with the
actual result. Rejection records the decision without dispatch. Existing persisted tool events
prevent replaying an already-recorded call during checkpoint recovery.

One approved music/video/render status check polls that same job in the host for up to
`STUDIO_MEDIA_WAIT_SECONDS` (default 600). It publishes elapsed time and available render
progress without repeated model polling or new approval cards. Timeout preserves the job ID;
it never counts as a completed export. Canonical bucket/output identifiers are taken from
the saved provider response rather than retyped model arguments.

Turn interruption runs concurrently with callback handling: Code Mode can issue several tool
calls at once, and the interrupt response can wait for those callbacks. While a pause is pending,
Studio answers the remaining callbacks as not run and never dispatches them to a provider.
MCP resources close without injecting the approval exception into their task groups, preserving
the checkpoint exception for the backend's approval handler.

Seedream size presets are expanded to the provider's exact dimensions before Gateway dispatch,
after pricing the original preset. This also supports older deployed validators that reject size
aliases. Lambda error payloads trigger refunds even when MCP's outer error flag is false.

This is not an exactly-once distributed execution guarantee: a worker crash after a remote
provider accepts a job but before its result is persisted still requires provider idempotency
or reconciliation. That boundary is not solved by a model harness.

Old *pending* Agents SDK `RunState` checkpoints cannot resume in Codex. They fail explicitly
and require a new Studio request; they are never silently replayed.

## Configuration and deployment

- `AGENT_MODEL` remains `gpt-5.6-luna` by default; existing `openai:` / `openai/` prefixes work.
- `OPENAI_API_KEY` and Gateway credentials stay in the existing backend secret configuration.
- `CODEX_RUN_TIMEOUT_SECONDS` defaults to 1800; each run also has a 160-tool-call ceiling.
- Each invocation uses a separate temporary workspace and Codex home. Host Codex configuration,
  plugins, shell tools, browsers, and direct image generation are not exposed to the manager.
- Local setup remains `bash scripts/setup_agent.sh`. The package installs the required runtime.
- The AgentCore image installs the same pinned runtime and checks `codex --version` during build.
  The locked distribution includes a Linux ARM64 wheel.

The existing SSE and artifact interfaces are retained. Studio adds execution `/stop` and
`/resume` routes, a public checkpoint timestamp, readable progress history, and inline media
results. Runtime changes require restarting the local backend or rebuilding the AgentCore
image; the media deployment script only updates provider targets and the Remotion site.

## Verification

`tests/test_codex_harness.py` exercises schema-checked discovery, structured output, progress,
approval/rejection, checkpoint isolation, duplicate-call recovery, and model failures. It also
starts the real pinned binary to verify native history restoration and runs its model/tool
loop against a local mock Responses endpoint. These tests do not call paid APIs.

```bash
RENDERHAUS_SECRETS_NAME='' .venv/bin/python -m unittest discover -s tests -q
RENDERHAUS_SECRETS_NAME='' .venv/bin/python scripts/ci_check.py
```

The CI checks cover provider schemas, imports, dry-run dispatch, and the Gateway Lambda package.
