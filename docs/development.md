# Day-to-day development

## Mental model

```text
Laptop (safe, free)          Cloud (real path)
─────────────────            ─────────────────
make web                     make gateway   → Lambda + Gateway (music tools)
make check                   make runtime   → AgentCore brain
                             make smoke
```

Dry-run switches live in Secrets Manager (`renderhaus/app`):

| Switch | Meaning when `true` |
|---|---|
| `SEEDANCE_DRY_RUN` | No paid video |
| `SEEDREAM_DRY_RUN` | No paid image |
| `MUREKA_DRY_RUN` | No paid music (local MCP **and** Lambda) |
| `GEMINI_TTS_DRY_RUN` | No paid TTS |

Only the value `false` turns a provider live.

## First-time setup

```bash
bash scripts/setup_agent.sh
# Bootstrap .env.local with AWS_REGION + RENDERHAUS_SECRETS_NAME
# Keep AGENTCORE_RUNTIME_ARN commented out for pure local work
make check
make web
```

`make web` starts the backend API only (`server/`, port 8000) — it doesn't serve a UI. For the
editor, also run the Next.js app under `web/` (see the root [README.md](../README.md)'s "Run the
app" section for the two-process setup).

## Daily local loop

1. `make dry-flags` — confirm dry-runs are `true` and whether cloud ARN/Gateway are set.
2. For local-only agent: remove `AGENTCORE_RUNTIME_ARN` from `.env.local` / secret override path.
3. `make web` (backend, :8000) + the Next.js app under `web/` (frontend, :3000) — see root README.
4. Change code → restart the relevant process if needed → retry.
5. `make check` before you push.

Handy:

```bash
make tools
make local-agent ARGS='list tools and propose a 10s workflow'
make lint
```

## Supervisor (Director → Executor)

Multi-shot productions use a typed plan, not a free-form LLM with paid tools:

1. **Director** (`agent/director.py`) — LLM emits `TypedProductionPlan` only.
2. **Executor** (`agent/executor.py`) — walks nodes → modality workers (`start_*` / `poll_*`).
3. **API** — `/api/productions` (plan → approve → run). The old static UI's Production tab was
   removed along with that frontend (see `design/MERGE_PLAN.md`); it's since been rebuilt as a
   real Next.js panel under `web/` (Production tab in the editor's icon rail — see
   `design/MERGE_STATUS.md` §4/§5 for current status and known gaps).
4. **CLI** — `make supervise ARGS='30s product teaser…'` (add `EXECUTE=1` to run workers).

```bash
make supervise ARGS='quiet luxury perfume teaser with soft piano'
# Review the JSON plan, then:
make supervise ARGS='…' EXECUTE=1
```

The CLI above and `/api/productions` directly both still work too, independent of the UI.
Workers respect `*_DRY_RUN` flags the same way as single-clip generates.

## When to deploy what

| You changed | Deploy |
|---|---|
| `mcps/mureka/**`, `lambdas/mureka/**`, `configs/mureka_gateway_tools.json` | **Gateway** |
| `agent/**`, other MCPs, `Dockerfile.agentcore` | **Runtime** |
| Both | **All** |
| Only the Next.js frontend (`web/**`) | Nothing in this table — that's a separate deploy (Cloudflare, per `design/ARCHITECTURE.md`), not AWS |

```bash
make gateway          # music Lambda + AgentCore Gateway
make runtime          # AgentCore Runtime container
make smoke
# or
make deploy-all
```

After gateway deploy, copy `AGENTCORE_GATEWAY_URL` from `.env.agentcore.gateway` into Secrets Manager if it changed, then redeploy runtime so the brain picks it up.

## GitHub Actions

| Workflow | When | What |
|---|---|---|
| [CI](../.github/workflows/ci.yml) | Every PR / push | Ruff + `scripts/ci_check.py` (no AWS spend) |
| [Deploy](../.github/workflows/deploy.yml) | Manual **Run workflow**, or push to `main` with path filters | Gateway and/or Runtime |

### One-time GitHub setup

Already automated for this repo via:

```bash
.venv/bin/python scripts/setup_github_oidc.py
```

That script creates/updates:

- IAM role `RenderhausGitHubActionsDeployRole` (OIDC trust for `half-cook/renderhaus-agent`)
- GitHub secrets `AWS_ROLE_TO_ASSUME` and `RENDERHAUS_SECRETS_NAME`
- GitHub Environment `production`

Re-run it if the role policy or repo name changes.

### Manual deploy from GitHub UI

Actions → **Deploy** → **Run workflow** → choose `gateway` / `runtime` / `all`.

### Auto on main

Pushing to `main` only deploys the slice whose paths changed (music stack vs agent runtime). CI still runs on every PR.

## Recommended habit

1. Build on laptop with all dry-runs **true**.
2. Push a PR → CI must be green.
3. Merge → auto gateway/runtime if paths match, **or** run Deploy manually.
4. Flip one dry-run to **false** in Secrets Manager only for a deliberate live test.
5. Flip it back to **true**.
