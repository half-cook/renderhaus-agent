# Renderhaus long-video program

This directory is the source of truth for turning Renderhaus from a single-clip generator into a
durable, agentic long-video production system.

Execution is tracked in the [Renderhaus Linear project](https://linear.app/fuck-tcf/project/renderhaus-a39791d4c15a),
which contains six dated milestones, assigned implementation issues, dependency relations, and
project-level architecture, evidence, and delivery documents.

## Documents

- [Product requirements](product/long-video-prd.md) — target users, promises, constraints, success
  metrics, and launch scope.
- [System design](architecture/long-video-system-design.md) — services, workflows, boundaries,
  failure handling, security, observability, and deployment topology.
- [Production manifest](architecture/production-manifest.md) — canonical domain model, lifecycle,
  schemas, invariants, and versioning.
- [Continuity and evaluation](architecture/continuity-and-evaluation.md) — memory packs, quality
  gates, critic rubrics, repair policy, and benchmark plan.
- [Delivery plan](plans/long-video-delivery-plan.md) — six two-week sprints, ownership model,
  dependencies, release gates, and team ceremonies.
- [Research evidence base](research/long-video-evidence-base.md) — primary-source evidence matrix,
  limitations, and bibliography supporting the design.
- [ADR-0001: durable workflow architecture](adr/0001-durable-production-workflows.md) — why workflow
  code owns execution while agents author typed production artifacts.

## Reading order

New contributors should read the PRD, system design, manifest, and delivery plan in that order.
Anyone changing generation, continuity, evaluation, or workflow behavior must also read the
evidence base and ADR-0001.

## Evidence policy

Architectural claims are linked inline to primary research papers or official documentation. The
evidence base labels each conclusion as demonstrated evidence, provider capability, or Renderhaus
engineering inference. Research results are directional rather than guarantees: many papers use
private models, limited benchmarks, or human evaluation protocols that do not reproduce the exact
Renderhaus stack. We therefore require internal acceptance tests before promoting a technique to a
production default.
