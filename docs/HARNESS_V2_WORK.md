# Harness v2 work plan

1. Read the poteto-mode principles and ground the existing system.
2. Frame. Extend the runner in eight test-first units. Paid calls remain mocked.
3. Design the workflow. Compare a sandbox default with virtual files plus an execution adapter.
4. Run the loop. Sandbox, inspection and rubric, effort, routing hints, questions, recovery, budget, then web.
5. Keep the audit trail in `harness-v2-decisions.tsv` as each unit is verified.
6. Verify and hand back. Run offline before/after evals, full Python checks, affected TypeScript checks, and Comet E2E when access is available. Commit locally only.

Completion requires the required commands to pass, reviewed changes committed on `feat/agent-harness-v2`, and honest reporting of incomplete browser or model validation.

Throughput checkpoint. Eight behavior units plus the eval and final verification. The first unknown is kernel isolation support. Native read-only design reviewers cover provider integration and question/budget ownership. External model lanes are omitted because live API calls are prohibited. No provider additions are planned; existing provider licences, IDs, prices, and routing aliases remain intact.

The selected design keeps checkpoint-backed virtual project files. A `SandboxBackendProtocol` adapter adds execution without changing their ownership. The job directory is exposed through `/work/` for SDK multimodal reads. A sandbox-default design was rejected because it would move project memory from checkpoint state to disk. The rubric grader has read-only tools and no dispatch or execution tools.

The installed Deep Agents audit checklist was applied to the final integration:

| Area | Integration and evidence | Remaining limit |
|---|---|---|
| Harness | Existing `create_deep_agent` graph retained; real graph tests | Pinned 0.7.23 is the signature authority |
| Skills | Existing SDK progressive loading and `metadata.gateway_tools` contract retained; inventory check | Role dispatch enforces scope; skill metadata is guidance |
| Subagents | Planner, media, audio, editor and general-purpose roles retained; native rubric grader added | Grader quality needs live calibration |
| Planning | SDK todo tools remain available; checkpoint tests | Deterministic evals cannot establish planning quality |
| Backend | Checkpoint virtual files plus sandbox execution and read-only `/skills/` and `/work/` routes; confinement tests | Deployment host must support isolation namespaces |
| Persistence | Existing Studio checkpointer, conversation scope and interrupt-ID checks; fresh-worker/resume tests | No new persistence service introduced |
| Approval | Native paid-call interrupts and separate question answers; autonomous paid-retry regression | Browser approval/question flow pending Comet access |
| Middleware | Existing summarization/caching integration retained; budget guards cover actual model calls; permissions and structured finish | Usage reconciliation retains ambiguous reservations |
| Streaming | Existing token/tool progress and saved provider-job polling retained; streaming tests | No live provider or model trial authorized |
| Evaluation | Routing checks and 58-case offline comparison with independent artifact verifiers | Semantic quality and typical live cost remain unverified |

Independent native review found concrete defects in quota mounts, stale revised media, grader pause propagation, revision-state reset, staging quotas and retry counting. The final regressions cover the accepted fixes. External model review was omitted under the live-call restriction. Browser observations remain blocked, separately recorded under ignored `.renderhaus/e2e/`.
