# Renderhaus Deep Agents audit

Audit baseline is `cde5e52` on `feat/deep-agents-audit`, inspected offline on
2026-10-08. The initial suite passed 370 tests. This document was written before
implementation. The tables describe the baseline; the verification record at the
end describes subsequent fixes.

There are 14 actionable findings: 5 fix now and 9 defer. Entries with no gap are
covered in the checklist and parameter tables but are not counted as findings.
Pricing, paid-tool approval policy, `APPROVAL_EXEMPT_TOOLS`, administrative
ElevenLabs approvals, and the Codex fallback remain constraints.

## Evidence and version authority

The local package is authoritative. No web documentation or live APIs were used.
The requested inspection ran with `.venv/bin/python`, because the shell has no
unqualified `python`. `deepagents.__version__` printed `0.7.23`.

```python
create_deep_agent(
    model=None, tools=None, *, system_prompt=None, middleware=(),
    subagents=None, skills=None, memory=None, permissions=None,
    backend=None, interrupt_on=None, response_format=None,
    state_schema=None, context_schema=None, checkpointer=None,
    store=None, debug=False, name=None, cache=None,
)
```

These are the real parameter names and defaults from `inspect.signature`.
`model` accepts a provider string or `BaseChatModel`; `subagents` accepts
`SubAgent`, `CompiledSubAgent`, or `AsyncSubAgent`. `backend` takes an instance,
not the backend factory shown in older skill examples. `checkpointer` accepts
`None`, a boolean, or a saver. See the installed
[graph assembly](../.venv/lib/python3.11/site-packages/deepagents/graph.py).

The following skill references were read in full. Short names in the tables
refer to these files.

| Reference | Skill |
| --- | --- |
| Audit | [deepagents-audit](/home/box/.agents/skills/deepagents-audit/SKILL.md) |
| Primer | [ecosystem-primer](/home/box/.agents/skills/ecosystem-primer/SKILL.md) |
| Core | [deep-agents-core](/home/box/.agents/skills/deep-agents-core/SKILL.md) |
| Memory | [deep-agents-memory](/home/box/.agents/skills/deep-agents-memory/SKILL.md) |
| Orchestration | [deep-agents-orchestration](/home/box/.agents/skills/deep-agents-orchestration/SKILL.md) |
| Middleware | [langchain-middleware](/home/box/.agents/skills/langchain-middleware/SKILL.md) |
| HITL | [langgraph-human-in-the-loop](/home/box/.agents/skills/langgraph-human-in-the-loop/SKILL.md) |
| Persistence | [langgraph-persistence](/home/box/.agents/skills/langgraph-persistence/SKILL.md) |
| Evals | [eval-engineering](/home/box/.agents/skills/eval-engineering/SKILL.md) and its discovery reference |

Package paths below are relative to `.venv/lib/python3.11/site-packages/`.
This clone contains the source for each cited module.

The skill examples disagree with 0.7.23 in several places. The installed
`graph.py` does not install todo middleware. `StateBackend()` resolves graph
state at call time rather than accepting a runtime. `StoreBackend` requires a
`namespace` factory and optionally an explicit store. Memory file loading does
not require a Store when it uses StateBackend. Declarative subagents can use
experimental fork mode, but Renderhaus uses isolated mode. The API supports
replacing core middleware by name; Renderhaus already uses that mechanism.

## Architecture and audit checklist

Studio and AgentCore enter `agent/studio_agent_next.py`. Backend selection
dispatches to `agent/deep_agent/runner.py` or `agent/studio_codex_runner.py`.
Both use `agent/gateway_executor.py` for schema validation, job reuse, progress,
and asset registration. `GatewayMCPServer` retains billing and transport.
The Deep Agents graph owns model calls, virtual files, delegation, and native
interrupts. `StudioCheckpointer` exports the saver into Studio conversation
storage and private AgentCore checkpoint SSE messages.

Each row answers used, wired correctly, gap, decision, and verification.

| Checklist item | Renderhaus baseline | 0.7.23 capability and skill evidence | Gap impact | Decision and check |
| --- | --- | --- | --- | --- |
| 1. Native agent construction | `runner.run_with_servers` compiles `create_deep_agent`, rather than a custom model loop. | Core, Primer; `deepagents/graph.py:create_deep_agent`. | none | Defer changes. Real compiled-graph tests already exercise this. |
| 2. Skills and progressive tools | `runner.py` supplies `/skills/` and a replacement `SkillsMiddleware` with dispatch tools. All six `skills/*/SKILL.md` files declare `metadata.include_tools`. Roles receive only their focused dispatch tools. | Core; `middleware/skills.py` reads metadata first, discloses tools after successful reads or pins, and caches metadata in thread state. | high for stale metadata after a skill update | Fix now F2. Reload the index on new turns and preserve native interrupted state. Test changed metadata and tool disclosure across fresh workers. |
| 3. Heavy-job subagents | Planner, media, audio, editor, and overridden general-purpose are isolated dict specs. Media covers generation and editing; editor covers assembly and export. No separate QC agent. Children return full file snapshots. | Orchestration; `middleware/subagents.py:SubAgent`, `CompiledSubAgent`; `middleware/async_subagents.py:AsyncSubAgent`. | high for stale sibling files; low for separate QC | Fix now F13, filter unchanged task files. Defer F4. Current workflows need existing schemas and inherited HITL. A QC agent needs a defined artifact inspection capability. Test focused tools, parallel files, and nested resume now. |
| 4. Planning | Roles have planning prose and project files, but no `write_todos` tool. A compiled baseline graph confirmed its absence. | Orchestration describes `TodoListMiddleware`; installed `graph.py` does not add it. `langchain/agents/middleware/todo.py` provides the middleware and state. | high | Fix now F1. Add middleware explicitly to manager and roles. Test saved todos and isolation from child planning. |
| 5. Backend and project memory | `CompositeBackend(default=StateBackend(), routes={"/skills/": FilesystemBackend(...)})`; skills are protected, other files persist within the conversation snapshot. Media assets use handles, not binary files. | Memory; `backends/state.py`, `composite.py`, `store.py`, `filesystem.py`. StateBackend is thread scoped; StoreBackend can persist across threads with an explicit namespace. | low for cross-conversation memory | Defer F5. Adding a durable store requires tenant isolation, migrations, and a project-memory ownership decision. Existing conversation-scoped memory is intentional. |
| 6. Persistence and resume | `checkpoints.py:StudioCheckpointer` exports storage, blobs, pending writes, and engine versions. `session_scope.py` hashes workspace, project, and conversation; approval scope also includes job. `Command(resume={interrupt_id: ...})` supports batches and nested tasks. | Persistence, HITL; `langgraph/checkpoint/memory/__init__.py`, `middleware/subagents.py` leaves child checkpointer unset to inherit parent persistence per invocation. | high for unbounded snapshots and remote crash windows | Defer F6. Retention must preserve DeltaChannel dependencies and pending child writes. Distributed durable storage is a separate deployment change. Fresh-worker, nested, rejected, batched, and foreign-scope tests already pass. |
| 7. Paid-tool HITL | `runner.py:needs_approval` unwraps dispatch calls and delegates to `tool_needs_approval`. Non-autonomous calls pause, autonomous calls follow existing authorization, ElevenLabs admin always pauses, NLE export stays exempt. Only approve and reject are supported by Studio. | Orchestration, Middleware, HITL; `langchain/agents/middleware/human_in_the_loop.py` supports `when` and approve, edit, reject. | high for missing explicit cost in native approval payload; none for current policy | Defer F7. Cost cards and edit decisions need coordinated Studio contracts. No price, exemption, autonomous, or decision-policy change in this audit. Existing policy tests remain mandatory. |
| 8. Context and middleware | Default summarization and prompt caching survive replacements by middleware name. `ToolStrategy(StudioAgentOutput)` validates final output. Graph recursion and run deadlines bound execution. | Core, Middleware; `graph.py`, `middleware/summarization.py`, `middleware/_prompt_caching.py`. Tool-call limits, fallback, and retries are separate LangChain middleware. | low for additional middleware | Defer F8 and F9. Avoid duplicate context middleware, unapproved model routing, and automatic retries of paid submissions. Final response structure already has a schema. |
| 9. Streaming and long jobs | `runner.py` listens only to `updates`; completed AI text becomes `MODEL_UPDATE`. Gateway emits actual starts, results, and wait progress. Saved jobs and checkpoints reach Studio incrementally. | Core, Persistence; compiled graph supports `astream` with `messages` and `updates`, including child namespaces. | high for delayed model text | Fix now F3. Emit bounded accumulating text with the existing progress contract. Test arrival before the next token and nested events without exposing tool arguments or reasoning. |
| 10. Evals | `tests/test_deep_agent.py` uses the real graph with a scripted model. Contract tests cover Studio jobs and AgentCore SSE. Codex fixtures remain active. No Harbor tasks or live model trajectories were supplied. | Evals requires reviewed Task Specs, controlled environments, independent verifiers, and real harness trajectories. | high for unmeasured model judgment | Defer F10. Offline scripted tests are contract checks, not capability scores. A scored harness run needs an approved model budget and controlled provider fixtures. |

## Every create_deep_agent parameter

All current wiring is in `agent/deep_agent/runner.py` unless another file is named.
Capability references here use Core plus `deepagents/graph.py:create_deep_agent`;
the additional skill or module named in a row supplies the relevant contract.

| Parameter | Current value and behavior | Installed capability | Gap impact | Decision |
| --- | --- | --- | --- | --- |
| `model` | Injected test model or `backend_config.deep_agent_model()`. Provider strings normalize OpenAI names. | String or `BaseChatModel`. `None` defaults to Anthropic and is deprecated; OpenAI strings use Responses API. | none | Defer changes. Explicit configuration avoids the deprecated default. |
| `tools` | Progress, read-only Studio context, and Gateway search. Provider dispatch exists only in skill middleware. | Adds tools to middleware tools, rather than replacing built-ins. | none | Defer changes. Do not expose dispatch eagerly or direct provider access. |
| `system_prompt` | Existing Studio manager rules plus Deep Agents routing, files, and approval instructions. | String or `SystemMessage`; model profile content may append to it. | low | Fix now F1 only for explicit multi-step todo guidance. |
| `middleware` | Replacement filesystem, skill disclosure, and `ProjectMemory` middleware. | Name-based replacements preserve default ordering. New entries precede the tail. | high | Fix now F1 adds todos. Retain built-in summarization and caching. |
| `subagents` | Five declarative role dictionaries with focused skill tools, files, memory, and inherited approval rules. Children return inherited files as well as their edits. | Declarative, precompiled, remote async, and experimental fork forms. See Orchestration and `middleware/subagents.py`. | high for parallel stale file updates | Fix now F13. Defer conversion F4. Existing dicts fit isolated model-led tasks. |
| `skills` | `["/skills/"]` on manager and all roles. | Backend-relative POSIX sources, metadata cache, and progressive disclosure. | high | Fix now F2 refreshes metadata only on ordinary turns. |
| `memory` | `["/AGENTS.md"]`; `memory.py:ProjectMemory` reloads file content instead of cached `memory_contents`. Child roles explicitly install it. | `middleware/memory.py` loads backend files into the prompt and optionally marks Anthropic cache blocks. See Memory. | low | Defer F11. The custom replacement omits `add_cache_control=True`; provider cache effectiveness needs provider-specific measurement. File refresh itself is correct. |
| `permissions` | Top-level parameter omitted. Replacement `FilesystemMiddleware` on every role receives `PERMISSIONS`, denying `/skills/**` writes. | Public top-level rules inherit to declarative children; `allow`, `deny`, and `interrupt` modes. `middleware/filesystem.py:FilesystemPermission`; first matching rule wins. | none | Defer wiring changes. Existing replacements already enforce the rule, remove shell tools, and are covered by a denied-write test. |
| `backend` | One CompositeBackend instance per request. StateBackend resolves the current graph context at call time; packaged skills use a bounded virtual filesystem. | Backend instance, Composite longest-prefix routing, State thread files, Store cross-thread namespaces. See Memory. | none | Defer changes F5. Host filesystem access is limited to packaged text skills, not project media or arbitrary host paths. |
| `interrupt_on` | Conditional predicates on three dispatch tools; inherited by declarative children. | Conditional native HITL supports action lists and per-interrupt resume maps. See Middleware and HITL. | none | Defer semantic changes F7. Preserve approve/reject, exemption, paid-tool and admin policy. |
| `response_format` | `ToolStrategy(StudioAgentOutput)` on manager. Child outputs are final text. | ToolStrategy, ProviderStrategy, AutoStrategy, schema type, or JSON schema. | none | Defer changes F8. Output remains the established Studio Markdown contract; no new job-spec schema is needed for these fixes. |
| `state_schema` | Omitted. Middleware contributes files, skills, and memory state. | Defaults to `DeepAgentState`, with DeltaChannel message storage. Custom types must preserve that reducer. | none | Defer changes. Todo middleware contributes its own state, avoiding a redundant schema. |
| `context_schema` | Omitted. Request-local tool closures capture Studio and executor; config carries thread identity. | Immutable run context passed to `create_agent`; `ToolRuntime` can access context. See Middleware. | low | Defer F12. Reusable graph caching could justify typed tenant context later; rebuilding the graph currently isolates request closures. |
| `checkpointer` | `StudioCheckpointer(thread_id, snapshot, sink)`. Restore rejects engine mismatches, validates encoded payloads, and disables pickle. | Optional saver; no durable saver is automatically created. Children inherit parent's saver when left unset. See Persistence. | high | Defer F6. Retain portable Studio snapshots; do not substitute an unpersisted InMemorySaver or stateful shared child saver. |
| `store` | Omitted. Cross-turn state persists through Studio rather than StoreBackend. | `BaseStore` for cross-thread storage; StoreBackend requires a namespace factory. See Memory and Persistence. | low | Defer F5 pending durable tenant-scoped storage design. |
| `debug` | Default `False`. | Runtime graph debugging. | none | Defer changes. Enabling logs adds no user benefit and may expose payloads. |
| `name` | Omitted on manager; child names are explicit. | Graph and tracing name. | low | Defer F12. A fixed name is optional observability metadata, not a runtime correctness fix. |
| `cache` | Omitted. Executor separately reuses completed call IDs and render jobs. | LangGraph node cache, distinct from provider prompt caching. | none | Defer changes F9. Caching paid tool nodes needs a side-effect and tenant-isolation contract. |

## Subagent choices and remaining middleware

| Role | Current behavior | CompiledSubAgent fit | AsyncSubAgent fit | Decision |
| --- | --- | --- | --- | --- |
| Planner | Prompt-led shot planning with files, context, and no paid dispatch. | Only if a deterministic typed planning workflow becomes a requirement. | No long provider job to delegate remotely. | Defer F4. Add todos with F1. |
| Media | Focused still and video dispatch through Gateway and native HITL. | Would require separately configuring approvals and file state inside the runnable. | Remote graph deployment adds a second approval and persistence boundary. Existing provider jobs are already tracked server-side. | Defer F4. Keep declarative inherited policy. |
| Audio | Focused audio providers, including always-interrupted ElevenLabs administration. | Same approval duplication as media. | Same remote state and policy problem as media. | Defer F4. Keep declarative inherited policy. |
| Editor | Remotion assembly, canonical poll IDs, final MP4 requirement, free NLE export. | Could fit deterministic export/QC when there is a stable contract; current editing remains model-led. | Existing Remotion jobs already have durable IDs and host polling. | Defer F4. Keep declarative inherited policy. |
| General-purpose | Overrides the upstream default and has no provider dispatch. | No deterministic graph needed. | No remote service needed. | Defer changes. Retain the restricted override. |

`CompiledSubAgent` and `AsyncSubAgent` do not inherit the parent's `interrupt_on`
configuration. That makes conversion a policy migration, not a safe shortcut.
Default isolated children inherit files but exclude messages, todos, skill
metadata, and private middleware state. Their returned file updates merge into
the parent. This is not equivalent to globally shared mutable project storage.

Summarization is already present on manager and children. Its installed factory
selects an 85% context trigger and 10% retention for models with a token profile,
or a 170,000-token trigger and six retained messages without a profile. It
archives evicted text through the backend and handles context overflow. The
default `DeepAgentState` reduces message checkpoint growth, but does not prune
the full exported history. Do not add a second summarizer.

Prompt caching is already installed for Anthropic and, when available, Bedrock
and Fireworks. Unsupported models are ignored. OpenAI provider caching is
separate. The custom ProjectMemory replacement currently omits the upstream
memory cache marker. F11 defers that optimization without claiming measured
cache savings.

The graph has a recursion limit of 180 and a default 1,800-second run timeout.
There is no explicit model-call or tool-call budget middleware. F9 defers a new
budget until its exhaustion and resume behavior is designed. Model fallback is
also absent. F8 defers it because it changes selected models and may require
another paid key. Provider SDK retries are not a guarantee of idempotent media
submissions. No generic tool retry is added.

Native approval requests carry provider name, exact compacted arguments, and
call IDs, but no explicit cost field. Billing remains in Gateway and
`server/billing_rates.py`; the Deep Agents predicate has no cost-based step-up.
F7 records the gap and leaves current spending authorization unchanged.

## Actionable finding register

| ID | Finding | Impact | Decision | Reason or planned verification |
| --- | --- | --- | --- | --- |
| F1 | Installed graph lacks todo planning. | high | fix now | Explicit TodoListMiddleware; compiled-graph persistence and role isolation tests. |
| F2 | Checkpointed skill metadata hides packaged skill updates across turns. | high | fix now | Reset metadata for new input, not Command resume; verify changed descriptions and disclosed tools. |
| F3 | Model text reaches Studio only after the complete model response. | high | fix now | Native message stream into existing MODEL_UPDATE events; observe partial output before completion. |
| F4 | Dedicated QC and alternate subagent forms are not justified by current workflows. | low | defer | Define real QC tools before adding roles. Compiled and async agents require their own approval wiring. |
| F5 | Project memory is conversation scoped rather than shared across conversations. | low | defer | Durable store and tenant namespace design are outside these safe fixes. |
| F6 | Snapshot retention and remote-worker crash windows remain open. | high | defer | DeltaChannel history and pending child writes require careful retention; distributed storage requires deployment changes. |
| F7 | Native approval cards lack explicit cost and edit decisions. | high | defer | Coordinated UI contracts and cost presentation are separate work; existing approval semantics are fixed by task scope. |
| F8 | No model fallback or separate structured job-spec pipeline. | low | defer | Existing final and Gateway schemas suffice. Do not introduce new paid keys or silently change models. |
| F9 | No explicit per-tool limits, generic retries, or node cache. | low | defer | Existing deadlines bound runs. Paid submission retry and cache safety need provider idempotency contracts. |
| F10 | No capability benchmark with real model trajectories. | high | defer | Evals requires reviewed tasks and budgeted harness runs; this task is offline. |
| F11 | Custom memory middleware omits the Anthropic cache marker. | low | defer | Optimization requires provider-specific measurement; no live cache calls in this task. |
| F12 | Immutable typed context and manager tracing name are not wired. | low | defer | Request closures already isolate tools; graph reuse and observability work can introduce these together. |
| F13 | Parallel subagents return full inherited file snapshots and can overwrite a sibling's edits with unchanged files. | high | fix now | `middleware/subagents.py` returns full non-private files. Filter task Commands to changed files relative to that task's input. Test parallel editing, independent file creation, and fresh-worker persistence. |
| F14 | HITL examines malformed wrapper arguments before normal tool validation and can crash on a missing `tool_name`. | high | fix now | Validate dispatch wrapper shape in the predicate; invalid calls reach normal recoverable tool validation. Verify no Gateway dispatch and unchanged approval behavior for valid calls. |

## Execution and verification plan

The pstack figure-it-out workflow for this audit is recorded here.

1. Read poteto-mode's Principles section and the requested LangChain skills.
2. Phase A, frame. Read all requested source, skill, test, and decision files,
   inspect installed signatures and middleware, and capture the 370-test baseline.
3. Phase B, design the workflow. Write this audit before code. Use existing
   middleware state shapes, new-turn inputs, and progress event contracts.
4. Phase C, run the loop. Write a failing test, apply the smallest fix, run
   focused graph and contract checks, and commit each fix independently.
5. Phase D, keep the audit trail. Append evidence and outcomes to
   `docs/deep-agent-decisions.tsv` without rewriting earlier migration records.
6. Phase E, verify and hand back. Run Ruff, the full unittest suite, dry-run CI,
   and the Studio TypeScript check. Inspect diffs and record blocked Comet E2E.

The throughput checkpoint is five implementation units plus this audit and a
final verification record. F13 and F14 were added after the native review
reproduced them, before their failing tests or implementation. No new dependency, UI contract, migration, push,
deployment, live API, or model-provider call is authorized. Pstack's external
Claude and Grok lanes are excluded by the offline constraint. Native review
reduces provider diversity and is not a cross-provider verdict.

Model the Domain keeps todos in TodoListMiddleware's schema and streamed text
in existing progress events. Laziness Protocol keeps each fix in the runner,
without a new service layer. Sequence work into verifiable units requires a red
test and green focused check per commit. Prove It Works requires a real compiled
graph for supporting checks and an honest browser blocker rather than an E2E pass.

Comet cannot be controlled in this environment, as specified by the user.
No browser actions have been performed. Planned browser scenarios cover a
multi-shot plan, updated skill behavior after a resumed conversation, partial
text progress, and paid-tool approval/rejection. Those checks remain blocked.

## Verification record

All five selected fixes are implemented. Each had a failing regression test
before its fix and a focused graph/contract check before its commit.

| Finding | Commit | Observed supporting check |
| --- | --- | --- |
| F1 | `99b4c58` | Two red tests became green. Todos survive JSON snapshot restoration; child todos do not replace the manager plan. 31 focused tests passed. |
| F2 | `dc2b7e5` | A changed skill description failed before reset. The next turn now reloads both description and `include_tools`; nested approval resumes still pass. 32 focused tests passed. |
| F13 | `10c22b1` | Parent read returned `Old brief` after concurrent work before the fix. Changed-file task Commands preserve the edited brief and independent audio file, including fresh-worker recovery. 33 focused tests passed. |
| F14 | `165cc06` | Four malformed wrapper cases crashed or interrupted before the fix. All now produce recoverable tool errors without Gateway dispatch. Valid paid, admin, autonomous, exempt, and nested cases still pass. 34 focused tests passed. |
| F3 | `56c48c7` | Two partial-stream regressions failed before message streaming. A third regression exposed internal summary text and became green after filtering. Partial text arrives before the next chunk, parent and child IDs remain distinct, and tool arguments stay out of progress. 37 focused tests passed. |

F13 filters unchanged inherited files; it does not resolve two intentional edits
to the same file. Such edits still need task ownership or a separate conflict
policy. F3 retains the existing 1,000-character progress limit. It does not
change final response delivery or provider job tracking.

Final checks all passed on the five-fix tree.

| Check | Result | Ignored local evidence |
| --- | --- | --- |
| `.venv/bin/ruff check agent lambdas scripts server providers` | Passed. | `.renderhaus/e2e/audit-ruff.log` |
| `.venv/bin/python -m unittest discover -s tests -q` | 378 tests passed, zero failures, errors, or skips. Baseline was 370; eight regression tests were added. | `.renderhaus/e2e/audit-unittest.log` |
| `.venv/bin/python scripts/ci_check.py` | Passed provider schemas, dry-run dispatch, imports, and actual Lambda ZIP assembly. | `.renderhaus/e2e/audit-ci.log` |
| Studio `./node_modules/.bin/tsc --noEmit -p .` | Passed. Temporary link to the supplied node_modules was removed. | `.renderhaus/e2e/audit-studio-tsc.log` |

Unittest and CI ran with `RENDERHAUS_SECRETS_NAME=""` and all nine requested
provider dry-run flags enabled. Tracing was disabled. Lambda packaging normally
invokes pip against an index. CI instead used `PIP_NO_INDEX=true` and an offline
wheelhouse recovered from existing cached wheel bytes. The first offline
attempt selected Python 2 tags for two dual-version wheels and failed dependency
resolution. Correcting the ignored recovery helper to select Python 3 tags made
the unchanged CI script pass. No package was downloaded and no check was mocked
or skipped. The helper is `.renderhaus/e2e/recover_cached_wheels.py`.

The native review independently passed all 37 focused tests and found no
remaining actionable defect. The scoped comment review found no new comments,
suppressions, or required deletions. External Claude and Grok review was not run
under the offline constraint; no cross-provider or different-family verdict is
claimed. The decision trail is `docs/deep-agent-decisions.tsv`.

Comet E2E remains **blocked**, recorded through
`python3 scripts/browser_e2e_hook.py record --report` in ignored
`.renderhaus/e2e/deep-agent-audit.json`. There was no browser interaction,
authenticated Studio validation, live model capability evaluation, live provider
call, or generated-media playback check. Contract tests are supporting evidence
only. No push or deployment occurred.
