# Production readiness — Renderhaus

Started 2026-08-06. Living document, same pattern as `MERGE_PLAN.md` — update it as we work through
today's session, don't let it drift from what's actually true. Status tags: `[DONE]`, `[IN PROGRESS]`,
`[TODO]`, `[BUG]` (broken today, not just unscaled), `[OPEN QUESTION]`.

## 1. Goal

Get `web/` (Next.js) + `server/` (FastAPI) from "works on one laptop" to able to safely serve
~100k requests/day — which in practice means: stateless, horizontally-scalable request handling;
durable state that survives a restart and is visible across replicas; infra provisioned safely
under concurrent boots; and baseline operational hygiene (tests, CI). Findings below come from
reading the actual code (`server/app.py`, `server/projects.py`, `server/assets.py`, `web/`), not
from the architecture docs' stated intentions — file:line references throughout so nothing here is
a guess.

## 2. Target architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Browser                                                                   │
└──────────────────────────────────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ CDN / edge (static assets, TLS termination)                       [TODO] │
└──────────────────────────────────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ web/ — Next.js, N stateless replicas                          [PARTIAL]  │
│  - editor UI, client-side timeline Command model                 [DONE] │
│  - sign-in (provider TBD, §4.5)                                  [TODO] │
│  - /api/* rewrite → backend (dev: same-origin proxy)              [DONE] │
└──────────────────────────────────────────────────────────────────────────┘
   │  HTTPS, bearer JWT (once §4.5 lands)
   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Load balancer (ALB / Cloud Run front door / equivalent)           [TODO] │
└──────────────────────────────────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ server/ — FastAPI, N stateless replicas                       [PARTIAL]  │
│  - JWT verification (server/auth.py, Clerk today — provider     [DONE*] │
│    open per §4.5, "*" = works today but not a settled decision)         │
│  - project/generation/production CRUD routes (server/app.py)     [DONE] │
│  - in-request ffmpeg calls block the event loop            [BUG] §4.1   │
│  - JobStore/ProjectStore/ProductionStore: local JSON,        [BUG] §4.2 │
│    in-process dict (three instances of the same pattern)                │
│  - generation + production jobs: in-process                  [BUG] §4.3 │
│    asyncio.create_task, no shared concurrency limit                     │
│  - S3 bucket / DynamoDB table created imperatively at boot   [BUG] §4.4 │
│  - CORS policy / rate limiting                                   [TODO] │
└──────────────────────────────────────────────────────────────────────────┘
   │                                    │
   ▼                                    ▼
┌───────────────────────────┐   ┌──────────────────────────────────────────┐
│ DynamoDB                   │   │ Job queue (Temporal — leaning, per §4.3;  │
│  - assets table    [DONE]  │   │ accepted in docs/adr/0001 — not yet built │
│  - jobs table       [TODO] │   │ for this path)                    [TODO] │
│  - projects table   [TODO] │   └──────────────────────────────────────────┘
│  - productions table[TODO] │                  │
└───────────────────────────┘                    ▼
                                   ┌──────────────────────────────────────────┐
                                   │ Worker pool — generation, production      │
                                   │ execution, ffmpeg merge, off the          │
                                   │ request-handling path               [TODO]│
                                   └──────────────────────────────────────────┘
                                                  │
                                                  ▼
                                   ┌──────────────────────────────────────────┐
                                   │ S3 (media) + generation MCPs              │
                                   │ (Seedance/Seedream/Mureka/Gemini TTS)     │
                                   │                                    [DONE]│
                                   └──────────────────────────────────────────┘
```

The shape of the fix, in one sentence: **everything in `server/` that isn't already S3/DynamoDB
needs to become either (a) stateless and safe to run N-wide, or (b) moved off the request path
entirely into a queue + worker pool** — nothing here needs a new pattern invented, it's applying
the pattern `server/assets.py` already uses (S3 + DynamoDB + presigned URLs) to the three places
that don't use it yet (jobs, projects, productions), plus getting the actual generation/production/
merge work off the request thread.

## 3. Issue index

Ranked by the order we're planning to work through them (see §6 for the dependency reasoning
behind this order — this isn't severity alone, it's "what has to be true before the next thing is
safe to build").

| Rank | § | Issue | Layer | Why this rank |
|---|---|---|---|---|
| 1 | 4.1 | Blocking `subprocess` calls inside async routes | Compute | Broken *today* at any concurrency, small fix, unblocks nothing else but nothing blocks it either — do it first and move on |
| 2 | 4.2 | `JobStore`/`ProjectStore`/`ProductionStore` on local JSON, in-process dict | State | Everything downstream (queueing, multi-replica deploy) needs durable shared state first |
| 3 | 4.4 | S3 bucket / DynamoDB table created imperatively at boot | Infra | Same moment as #2 — new tables should be provisioned correctly from day one, not retrofitted |
| 4 | 4.3 | Generation + production jobs run as in-process `asyncio.create_task`, no shared concurrency limit | State | Needs #2's durable job rows to enqueue against; biggest single lift in this doc |
| 5 | 4.6 | No Dockerfile for `server.app`, no worker model | Deploy | Adding replicas is only safe once #2–#4 remove the state-sharing problems |
| 6 | 4.7 | No CORS policy / rate limiting for a non-proxied prod topology | Networking | Depends on the deploy topology decided in #5 |
| 7 | 4.5 | No auth integration in `web/` (provider TBD — see below) | Auth | Feature-completeness gap, not a scaling blocker — parallelizable with the rest, not sequenced by them |
| 8 | 4.8 | Zero test coverage | Quality | Backfilled alongside each fix above, not a standalone phase |
| 9 | 4.9 | CI partially in place (backend lint only, merged 2026-08-07); no `web/` job, no `server.app` deploy path, no real tests | Quality | Remaining gaps still cheapest to close once #8 gives it something to run |

## 4. Issues → reconciliation

### 4.1 Blocking `subprocess` calls inside async routes — `[BUG]`

**Where**: `server/projects.py:218,245,314,387` (`probe_media_duration`, `_has_audio_stream`,
`merge_video_paths`, and one more) call `subprocess.run` directly. Reached from `async def` routes,
e.g. the `/api/projects/{id}/merge` handler at `server/app.py:1225`.

**Why it matters now, not just at scale**: `subprocess.run` blocks the calling thread. FastAPI/
uvicorn runs the event loop on one thread by default, so one in-flight ffmpeg merge freezes every
other concurrent request on that process — health checks, unrelated users' API calls, everything —
until ffmpeg exits. This is true at 10 req/day, not just 100k.

**Reconciliation**: wrap every `subprocess.run` call in `await asyncio.to_thread(...)`, or move the
whole merge/probe operation off the request path per §4.3 (better — see below, since merges are
exactly the kind of job that shouldn't hold an HTTP request open anyway).

**Moving pieces**:
- [ ] Decide: quick fix (`asyncio.to_thread` wrap, keeps synchronous request/response shape) vs.
      full fix (merge becomes a queued job, `/merge` returns immediately with a job id) — the full
      fix subsumes this issue into §4.3's work, so probably don't do both.
- [ ] If quick fix: wrap the four call sites, add a regression test that fires concurrent requests
      during a merge and asserts the others aren't blocked.
- [ ] If full fix: no separate work here, tracked under §4.3.

### 4.2 `JobStore` / `ProjectStore` / `ProductionStore` on local JSON, in-process dict — `[BUG]` (scaling)

**Where**: `server/app.py:147` (`JobStore`), `server/projects.py:45` (`ProjectStore`), and — added
2026-08-07, merged in from `renderhaus-agent/main` — `server/productions.py:41` (`ProductionStore`,
backing the new brief→plan→approve→execute Production feature) all keep a `dict[str, Any]` in
memory, loaded from `*.json` files under `.renderhaus/web-jobs/`, `.renderhaus/projects/`, and
`.renderhaus/productions/` respectively on startup (`JobStore.load`, `server/app.py:153`), each
guarded by its own process-local `asyncio.Lock`. Three independent instances of the identical
pattern now, not two.

**Why it matters**: two replicas behind a load balancer don't share memory or (usually) disk.
Replica A creates a project; a request routed to replica B can't see it. Most container platforms
(ECS Fargate, Cloud Run, k8s without a persistent volume) also wipe local disk on every
restart/redeploy/scale-down, so even single-replica deployments lose all job/project/production
history on every deploy.

**Reconciliation**: replace all three stores with DynamoDB tables, following the exact pattern
`server/assets.py` already uses for the assets table (`AWS_DYNAMODB_ASSETS_TABLE`, auto-created —
see §4.4 for why that auto-create part specifically needs to change). Three new tables: jobs,
projects, productions. Keep the same public shape (`ProjectStore`/`JobStore`/`ProductionStore`
method signatures) so `server/app.py` doesn't need route-level changes — swap the storage engine
underneath.

**Moving pieces**:
- [ ] Design the DynamoDB item shape for jobs, projects, and productions (partition key, any GSIs
      needed for "list projects by user" / "list jobs by project" / "list productions by user"
      queries the current code does over the in-memory dicts).
- [ ] Port `JobStore` (`server/app.py:147`) to a DynamoDB-backed implementation with the same
      interface (`load`, `create`, `get`, `put`, list-by-user).
- [ ] Port `ProjectStore` (`server/projects.py:45`) the same way.
- [ ] Port `ProductionStore` (`server/productions.py:41`) the same way.
- [ ] Decide what happens to the resumable-job-on-restart logic in `JobStore.load`
      (`server/app.py:153-192`) — DynamoDB doesn't need a disk-scan-on-boot step, but the
      "mark stuck jobs as failed on restart" semantics still need a home (probably a scheduled
      sweep, not a boot-time scan).
- [ ] Migration: is there existing local `.renderhaus/` data worth carrying over, or is this a
      clean cutover? (Probably clean cutover for a pre-launch repo — confirm.)

### 4.3 Generation jobs as in-process `asyncio.create_task` — `[BUG]` (scaling)

**Where**: `_start_task` (`server/app.py:852`) does `asyncio.create_task(_run_generation(...))`,
tracked in `app.state.generation_tasks`. Called from job creation and refinement
(`server/app.py:1365,1494`). Added 2026-08-07: the new Production feature has its own equivalent,
`_start_production_task` (`server/app.py:1008`), tracked in `app.state.production_tasks` — same
in-process, non-durable pattern, second instance of it.

**Why it matters**: the task exists only in that process's event loop. It doesn't survive a
restart (there's already a partial workaround for this — `JobStore.load` marks jobs as `failed` on
boot if they weren't far enough along, `server/app.py:153-192` — which is itself a symptom of not
having a durable queue), and it can't be picked up by a different replica than the one that
started it. `docs/architecture/long-video-system-design.md` names durable workflow orchestration as
the design target — see the correction below on which engine is actually accepted for that — but
it isn't implemented for the current web app path (either job kind).

**Correction (2026-08-07)**: this section originally named "Inngest/Trigger.dev" as a candidate,
sourced from `ARCHITECTURE.md`'s informal placeholder. That's not the accepted decision —
`docs/adr/0001-durable-production-workflows.md` formally accepts **Temporal** for exactly this
problem (durable orchestration of expensive external side effects, idempotency so paid generation
calls never double-fire, crash recovery). Weighed against Inngest in discussion; leaning Temporal
specifically because it's already the accepted ADR and today's simple job shapes are a strict
subset of what it's designed for (see the operation inventory pulled together 2026-08-06 across
both `ARCHITECTURE.md` and `docs/architecture/long-video-system-design.md` — still not written up
as a standalone doc section, worth doing before this is decided for real).

**New finding (2026-08-07): the two in-process task paths don't even share a concurrency limit.**
`generation_slots = asyncio.Semaphore(2)` (`server/app.py:276`) is acquired inside
`_run_generation` (`server/app.py:639-640`) — it only guards the single-clip `/api/generations`
path. The Production executor (`agent/executor.py`'s `run_plan`, fans out independent plan nodes
via plain `asyncio.gather`) calls the same underlying generation workers with **no semaphore at
all** — a single Production plan with N independent nodes fires N concurrent provider calls,
uncapped, on top of whatever's already running through the semaphore-guarded path. The
semaphore-of-2 was already a crude stand-in before this; now it isn't even consistently applied.
This is exactly the kind of thing a real queue with proper concurrency controls fixes by
construction (one place to configure it, covering every job kind) rather than something to
patch in two places by hand.

**Reconciliation**: move job execution (generation calls, production execution, and the `/merge`
ffmpeg work from §4.1) into a real queue + worker pool. `server/app.py` route handlers become
thin: validate, write a `queued` row to DynamoDB (§4.2), enqueue, return the job/production id
immediately. A separate worker process (not the request-handling replicas) consumes the queue and
does the actual work — generation, production execution, and merge all become jobs in the same
system rather than three different in-process patterns. Frontend polling (`GET /api/generations/{id}`,
`GET /api/productions/{id}`) doesn't change shape.

**Moving pieces**:
- [ ] **[OPEN QUESTION]** Queue technology — Temporal vs. Inngest vs. other, per the correction
      above. Still the single biggest architecture decision in this whole doc.
- [ ] Define the worker process: a separate deployable (own Dockerfile/entrypoint) that consumes
      the queue, reuses `agent/service.py`'s generation logic, `agent/executor.py`'s production
      logic, and `server/projects.py`'s merge logic.
- [ ] Rework `/api/generations`, `/api/productions/*`, and `/api/projects/{id}/merge` to enqueue
      instead of `asyncio.create_task`.
- [ ] Replace the semaphore-of-2 with a real concurrency/rate control at the queue layer, covering
      both generation and production jobs uniformly (see the new finding above).
- [ ] Decide fate of the restart-resume logic in `JobStore.load` once a real queue provides
      redelivery/retry — likely simplifies or goes away entirely.

### 4.4 Infra created imperatively at boot — `[BUG]` (once N>1)

**Where**: `init_assets_db()` (`server/assets.py:206`, called from the FastAPI `lifespan` at
`server/app.py:862`) calls `client.create_table(...)` (`server/assets.py:133`) and
`client.create_bucket(...)` (`server/assets.py:173,175`) if they don't already exist.

**Why it matters**: with one instance this is a convenience. With N replicas starting concurrently
(a deploy, an autoscale event), multiple processes race to create the same table/bucket — usually
survivable (idempotent-ish AWS errors get swallowed) but not something to rely on, and it means the
app's IAM role needs `dynamodb:CreateTable` / `s3:CreateBucket` permanently, which is broader than
a running API server should need (least-privilege: it should only need read/write on resources
that already exist).

**Reconciliation**: provision the DynamoDB tables (assets — already exists; jobs, projects — new,
per §4.2) and S3 bucket via IaC (Terraform or CDK — pick one, see open question below) as a
separate deploy step, not app code. `init_assets_db()` becomes a startup *check* (fail fast with a
clear error if the table/bucket is missing) instead of a create.

**Moving pieces**:
- [ ] **[OPEN QUESTION]** Terraform vs. CDK vs. Pulumi — depends on what else the infra around
      this ends up being provisioned with (load balancer, container platform, VPC if any). Worth
      deciding once alongside §4.6's platform choice, not in isolation.
- [ ] Write IaC for: S3 bucket, DynamoDB assets/jobs/projects tables, the IAM role/policy the app
      actually needs (read/write on named resources, not create/delete).
- [ ] Change `init_assets_db()` to check-and-fail-fast instead of create-if-missing.
- [ ] Same treatment for anything AgentCore-related that's currently manual (`scripts/deploy_agentcore.py`
      — out of scope for this pass unless it turns out to matter for the 100k/day path).

### 4.5 No auth integration in `web/` — `[TODO]`, provider not yet decided

**Where**: `server/auth.py` currently verifies Clerk JWTs server-side (pre-existing, from
renderhaus-agent), but `web/package.json` has no auth dependency of any kind and nothing under
`web/src` references sign-in. Consistent with `ARCHITECTURE.md` marking auth `[PLANNED]`, but it
means the auth boundary the backend already expects is currently unreachable from the actual UI.

**Open call, deliberately not resolved here**: Clerk being already wired into `server/auth.py` is
an inherited decision, not a settled one — worth treating as open rather than assumed. Whatever we
pick needs to work on both sides (frontend sign-in/session UI, backend token verification), so
this is one decision, not "pick a frontend library."

> **Note (2026-08-06):** Clerk is a placeholder, not the final answer. It's what's already
> partially wired in server-side, so it's what's named in the diagram/moving-pieces below for now,
> but we're explicitly not committing to it — we'll come back and settle this properly.

**Reconciliation**: parked until the provider decision is made. Once decided, the shape is the
same regardless of provider: frontend sign-in UI + session, a way to attach the session credential
to requests going through the `/api/*` proxy, and (if the provider changes) a corresponding rewrite
of `server/auth.py`'s verification logic.

**Moving pieces**:
- [ ] **[OPEN QUESTION]** Auth provider: keep Clerk (already partially built server-side) vs.
      something else (Auth.js/NextAuth, AWS Cognito — fits the existing AWS-native stack — or
      other). Discuss separately before starting implementation.
- [ ] Once decided: frontend sign-in/sign-up UI + session handling.
- [ ] Attach the session credential to backend calls through the `/api/*` proxy.
- [ ] Confirm whatever the provider's "authorized origins" concept is (Clerk's
      `CLERK_AUTHORIZED_PARTIES`, already updated in `README.md` per `MERGE_PLAN.md`, or the
      equivalent for a different provider) covers the real prod frontend origin, not just
      `localhost:3000`.

### 4.6 No Dockerfile for `server.app`, no worker model — `[TODO]`

**Where**: the only Dockerfile in the repo, `Dockerfile.agentcore`, is specific to Bedrock
AgentCore (`linux/arm64`, port 8080, `CMD ["uvicorn", "agent.runtime_app:app", ...]`) — it doesn't
run `server.app` at all. Locally, `server.app` runs via a bare `uvicorn.run(..., reload=False)`
(`server/app.py:1501`), single process, no worker count.

**Reconciliation**: a real container image for `server.app`, run with multiple uvicorn workers (or
multiple container replicas — likely both: N containers × M workers each), behind the load
balancer in §2's diagram. Once §4.2–4.3 land, this becomes safe to actually scale horizontally
(right now, adding replicas would just make the state-sharing problems in §4.2/4.3 worse, so this
should land after those, not before).

**Moving pieces**:
- [ ] **[OPEN QUESTION]** Deploy target — ECS Fargate, Cloud Run, EKS/k8s, something else? Drives
      the Dockerfile shape and whether "workers" means uvicorn `--workers N` inside one container
      or just more container replicas (usually you want both, in moderation).
- [ ] Write the Dockerfile for `server.app`.
- [ ] Decide process manager: plain `uvicorn --workers N` vs. gunicorn+uvicorn workers (gunicorn
      gives you worker restarts/health management that plain uvicorn doesn't).
- [ ] Health-check endpoint — `/` currently returns a static JSON status
      (`server/app.py`, post-`MERGE_PLAN.md` §7 cleanup); decide if that's sufficient for a
      liveness/readiness probe or if it needs to check DynamoDB/S3 connectivity.

### 4.7 No CORS policy / rate limiting for a non-proxied prod topology — `[TODO]`

**Where**: no `CORSMiddleware`, no rate-limiting middleware anywhere in `server/app.py`. Currently
fine because dev traffic is same-origin through the Next.js `rewrites()` proxy
(`web/next.config.ts`, from `MERGE_PLAN.md` §5 step 9) — but that's a dev-time convenience, not a
decided production topology.

**Reconciliation**: depends on the prod topology decision — if `web/` keeps proxying to `server/`
at the edge/CDN layer in production too (recommended: keeps the browser same-origin, no CORS
needed, matches dev), CORS stays a non-issue; if the frontend and backend end up on genuinely
different origins in prod, `CORSMiddleware` becomes required. Rate limiting is needed either way
before opening this up to real traffic — a small number of endpoints (generation, merge) trigger
real spend (Seedance/Seedream/Mureka calls), so unrestricted request volume is a cost/abuse risk,
not just a load risk.

**Moving pieces**:
- [ ] **[OPEN QUESTION]** Decide prod topology: edge-proxied same-origin (no CORS needed) vs.
      separate origins (CORS needed). Affects §4.6's deploy shape too.
- [ ] Add rate limiting — at minimum on `/api/generations` and `/api/projects/{id}/merge` (the
      spend-triggering endpoints), likely via API-gateway-level throttling if there's a gateway in
      front, or `slowapi`/similar in-app otherwise.

### 4.8 Zero test coverage — `[TODO]`

**Where**: no test files for either app's own code anywhere in the repo (confirmed by search —
only hits were inside a third-party package's `node_modules`).

**Reconciliation**: not a blocker for a first deploy, but every fix above (concurrency, storage
migration, queueing) is exactly the kind of change that's easy to silently break without tests.
Sequence test-writing alongside each fix above rather than as one big separate effort — e.g., the
`asyncio.to_thread`/concurrency fix in §4.1 should ship with the concurrent-request regression test
mentioned there.

**Moving pieces**:
- [ ] Pick a Python test runner/setup (pytest, presumably — not currently in `pyproject.toml`
      dependencies).
- [ ] Pick a frontend test setup for `web/` (nothing currently configured — Vitest/Jest +
      Testing Library would be the standard Next.js choice).
- [ ] Backfill tests for the DynamoDB-backed stores (§4.2) and queue integration (§4.3) as they're
      built, not after.

### 4.9 No CI — `[PARTIAL]`, updated 2026-08-07

**Where**: `.github/workflows/ci.yml` and `.github/workflows/deploy.yml` merged in from
`renderhaus-agent/main` (2026-08-07). CI runs `ruff check agent mcps lambdas scripts server` (we
added `server` to that list during the merge reconciliation — it was previously `agent mcps
lambdas scripts` only, and before this merge, `server`/`web` was never linted at all) plus
`scripts/ci_check.py` — schema/import/config sanity checks, not real tests. Deploy is OIDC-based
(`scripts/setup_github_oidc.py`), covers the Mureka Lambda gateway and the AgentCore runtime.

**What's still missing**: `web/` (Next.js) has no CI job at all — no lint, no typecheck, no build
check on PRs. Neither workflow covers a deploy path for `server.app` itself (§4.6). And
`scripts/ci_check.py` is smoke checks, not a test suite — §4.8 (zero test coverage) is still fully
true; CI existing doesn't mean anything is tested yet, just that syntax/import breakage and
`server/`'s narrow ruff rules (`E9`, `F` minus `F401` — see `pyproject.toml`) get caught.

**Reconciliation**: add a `web/` job to `ci.yml` (`npm run lint`, `npx tsc --noEmit`, tests once
§4.8 lands), and a deploy path for `server.app` once §4.6's Dockerfile/deploy-target decisions land.

**Moving pieces**:
- [ ] Add a `web/` CI job (lint, typecheck, build; tests once §4.8 lands).
- [ ] Extend `deploy.yml` (or add a parallel workflow) to cover `server.app` once §4.6 exists.
- [ ] Backfill real tests behind `scripts/ci_check.py`'s smoke checks as §4.8 progresses.

## 5. Open questions requiring a decision before implementation

Pulled together from §4 so they're not buried:

- **[OPEN QUESTION] Job queue technology** (§4.3) — Temporal (accepted in `docs/adr/0001`, leaning
  this way) vs. Inngest vs. other. Biggest single decision in this doc. Note the new evidence from
  2026-08-07: the just-merged Production feature (`agent/executor.py`) was built with plain
  `asyncio`, not Temporal, despite the ADR — worth weighing before treating the ADR as settled in
  practice, not just on paper.
- **[OPEN QUESTION] IaC tool** (§4.4) — Terraform vs. CDK vs. Pulumi.
- **[OPEN QUESTION] Auth provider** (§4.5) — keep Clerk (already partially built server-side) vs.
  something else. Deliberately not resolved in this doc — raised 2026-08-06, discuss separately.
- **[OPEN QUESTION] Deploy target** (§4.6) — ECS Fargate vs. Cloud Run vs. EKS/k8s vs. other.
- **[OPEN QUESTION] Prod topology** (§4.7) — edge-proxied same-origin vs. separate frontend/backend
  origins.
- **[OPEN QUESTION] Frontend framework** (not in §4 — a pre-existing choice, not a gap) — `web/`
  uses Next.js 16.2.12; the earlier `spikes/timeline-render` spike used plain Vite + React + TS
  instead. Raised 2026-08-06: worth a real discussion if there's an appetite to reconsider, since
  this pinned Next version has non-standard APIs per `web/AGENTS.md` (added risk beyond normal
  framework overhead). Not blocking anything above — noted here so it doesn't get lost, not
  because it's on the critical path.

## 6. Suggested sequencing

Not a hard order, but dependencies matter: §4.2 (durable state) and §4.3 (durable queue) block
§4.6 (multi-replica deploy) from being safe — adding replicas before fixing state-sharing just
multiplies the bugs. §4.1 is small and stands alone; do it whenever, though it's subsumed if §4.3
lands first. §4.4 should land alongside §4.2 (new tables need the same "provisioned by IaC, not
app code" treatment as day one, not retrofitted). §4.5, §4.8, §4.9 don't block anything else and
can run in parallel with the rest.
