# Deep Agents migration plan

The completion gate is a default Deep Agents runner that preserves Studio requests, outputs,
approvals, progress, asset registration, and conversation recovery. Offline graph tests must
exercise the real compiled graph with a fake model. Full provider and browser verification
remains pending because Comet, a Clerk session, and paid provider credentials are unavailable.

## Workflow

- Read the Principles section of poteto-mode. Completed.
- Phase A: Frame. Inspect Studio, Gateway, runtime contracts, installed Deep Agents APIs, and baseline tests.
- Phase B: Design the workflow. Compare integration behind the existing contract with a service rewrite.
- Phase C: Run the loop. Extract and verify shared Gateway policy. Add and verify the graph. Switch callers and verify the contract. Document and run the full checks.
- Phase D: Keep the audit trail. Append decisions to `docs/deep-agent-decisions.tsv` at each gate.
- Phase E: Verify and hand back. Inspect the diff, run offline tests, lint and CI checks, and record blocked browser E2E.

## Design

The existing `StudioAgentRequest`, `StudioAgentOutput`, `StudioAgentContext`, and approval
exception remain the public boundary. `GatewayExecutor` owns schema validation, job reuse,
canonical provider identifiers, polling, and asset harvesting. `GatewayMCPServer` retains
transport, asset-handle resolution, and billing.

The new graph owns the model, progressively disclosed skills, role-specific subagents, virtual
files and memory, checkpoints, and native HITL interrupts. Portable checkpoints travel through
existing conversation storage so a fresh local or AgentCore worker can resume. Thread IDs bind
workspace, project, and conversation. No database or Studio UI migration is needed.

A neutral service rewrite was considered. It would move the contracts and runtime entrypoint
and require import and persistence migration. The smaller adapter design preserves established
callers and lets both backends share the critical execution policy.

The architecture lane used native Codex. External Claude and Grok lanes are unavailable under
the task's offline and no-paid-API constraint. Provider diversity is reduced; no external model
calls were made. Browser verification is blocked, not passed.

## Throughput checkpoint

Four units produce three implementation commits after the policy extraction. Each unit ends
with focused tests before the next begins. Checks use `.venv/bin/python`, because `python` is
absent and system `python3` has no project dependencies. The supplied venv baseline ran 138
tests with no failures or errors. Local `main` and the starting branch have the same commit.
The reported single error on main was not reproduced in this environment.
