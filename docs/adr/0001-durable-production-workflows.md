# ADR-0001: durable workflows with typed agent artifacts

**Status:** Accepted for implementation  
**Date:** 2026-07-12

## Context

Renderhaus currently performs one LLM-mediated provider submission followed by in-process polling.
A long production contains dozens of dependent and parallel operations, expensive external side
effects, approval pauses, targeted repairs, and final assembly. It must survive process restarts and
must not duplicate paid generation.

Research supports specialized planning roles. MovieAgent uses hierarchical director, scene, and
shot reasoning ([Wu et al., 2025](https://arxiv.org/abs/2503.07314)); FilmAgent reports benefits
from iterative role collaboration over intermediate production artifacts
([Xu et al., 2025](https://arxiv.org/abs/2501.12909)); DreamFactory uses multi-agent collaboration
and iterative keyframes ([Xie et al., 2024](https://arxiv.org/abs/2408.11788)). These papers do not,
however, establish that an unconstrained agent loop is safe for durable paid execution. That is an
engineering requirement specific to Renderhaus.

## Decision

Use Temporal as the durable orchestration engine. Implement one `ProductionWorkflow` per film and
child workflows for large scene/shot batches if history size requires it. Model LLM, provider,
storage, database, evaluation, and media operations as idempotent activities. Use Temporal signals
or updates for approval, pause, resume, shot replacement, and budget changes.

Agents operate only inside bounded activities. They consume typed production artifacts and emit
typed proposals. Deterministic policy code validates and applies those proposals. Agents never own
provider polling, retry loops, concurrency, budgets, or workflow transitions.

Temporal is designed to resume executions after crashes and network failures
([Temporal documentation](https://docs.temporal.io/)). Google’s official durable-agent example
persists model and tool calls as Temporal activities so recovery neither loses state nor repeats
completed calls ([Google durable-agent example](https://ai.google.dev/gemini-api/docs/temporal-example)).

## Alternatives considered

### Continue with `asyncio` tasks and JSON files

Rejected for long-form production. It is simple but requires custom recovery, timers, distributed
locking, idempotency, approval signals, event history, migrations, and operational inspection. The
current implementation can resume polling one known task but cannot safely reconstruct an entire
production graph.

### LangGraph persistence

Viable for prototyping. LangGraph provides checkpointers, stores, durable graph state, and
interrupts ([LangGraph persistence](https://langchain-ai.github.io/langgraph/cloud/concepts/threads/),
[LangGraph interrupts](https://langchain-ai.github.io/langgraph/concepts/breakpoints/)). We are not
selecting it as the execution backbone because the dominant difficulty is durable orchestration of
many slow external side effects rather than conversational state. LangGraph may still implement a
bounded planning subgraph inside an activity.

### Fully autonomous multi-agent swarm

Rejected. Role-based research supports decomposition, but a swarm would make cost, termination,
replay, authorization, and debugging harder. Renderhaus uses specialized roles as explicit nodes
whose inputs and outputs are inspectable.

### Build a custom database queue

Deferred. It could meet the requirements but would recreate workflow history, durable timers,
retries, signals, heartbeats, and replay tooling already supplied by Temporal.

## Consequences

Positive:

- Crash recovery and human approval are first-class.
- Paid side effects gain explicit idempotency and reconciliation boundaries.
- Workflow history makes a production explainable.
- Independent shots can run concurrently with bounded semaphores.
- Agent logic is testable separately from execution logic.

Costs:

- Temporal adds infrastructure and deterministic-workflow constraints.
- Workflow/activity schema changes require versioning discipline.
- Large productions must control workflow history size.
- Developers need local Temporal tooling and replay tests.

## Guardrails

- No network, random, clock, filesystem, subprocess, or model operation in workflow code.
- Record intent before every non-idempotent side effect.
- Use stable activity IDs derived from production revision, entity, operation, and attempt.
- Never resubmit a provider task while submission status is unknown.
- Cap generation and critic attempts in manifest policy.
- All approvals bind to a manifest revision and cost estimate; later material changes invalidate
  approval.
- Every workflow change must pass history replay tests.
