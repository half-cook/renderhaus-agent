# Renderhaus

AI video production Studio: a Next.js canvas backed by FastAPI, durable agent runs,
media providers, approvals, and asset storage.

## Run locally

Requires Python 3.11+, Node.js 20+, and ffmpeg/ffprobe for local media processing.

1. Install the backend and Studio dependencies:

   ```bash
   make setup
   npm ci --prefix studio
   ```

2. Configure the backend in `.env.local` or the existing AWS Secrets Manager secret
   (`renderhaus/app` by default). `server/config.py` defines defaults;
   `scripts/sync_secrets.py` syncs an existing local configuration. Keep secrets out of Git.

   - Agent: `OPENAI_API_KEY` and `AGENTCORE_GATEWAY_URL`. Codex is the default harness;
     `AGENT_MODEL` defaults to `gpt-5.6-luna`. [Harness configuration](docs/CODEX_HARNESS.md).
   - Authentication: run `make setup-clerk` to link Studio to the shared Clerk application.
     Set matching `CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` on the backend.
     `CLERK_AUTHORIZED_PARTIES` must include the exact Studio origin, normally
     `http://localhost:5174`. Authenticated deployments require matching frontend/backend keys.
   - Assets: `AWS_REGION`, `AWS_S3_BUCKET`, and `AWS_DYNAMODB_ASSETS_TABLE`
     (default `renderhaus-assets`), with AWS credentials available to the process.
     Media bytes use S3; asset metadata uses DynamoDB. Studio project state uses SQLite.

3. Start the two services in separate terminals:

   ```bash
   make backend  # FastAPI on :8000
   ```

   ```bash
   make studio   # Next.js on localhost:5174
   ```

Open [localhost:5174](http://localhost:5174). Studio proxies `/api/*` to FastAPI.
Keep the configured `localhost` hostname when starting Next.js.

Provider dry-run flags default to true. A dry-run produces no generated media.
Live calls need the provider's configured credentials and existing spending approval.
For local assembly and the optional local Gateway, see [local assembly](docs/LOCAL_ASSEMBLY.md).
Deep Agents is opt-in with `RENDERHAUS_AGENT_BACKEND=deepagents`; its model and role
settings are documented in [Deep Agents](docs/DEEP_AGENT.md).

## Check changes

The setup script installs the application. Install test tools once:

```bash
.venv/bin/python -m pip install ruff pytest pytest-asyncio 'moto[s3]>=5'
```

```bash
make lint
RENDERHAUS_SECRETS_NAME='' .venv/bin/python -m pytest -q
RENDERHAUS_SECRETS_NAME='' make check
cd studio
node --test tests/*.test.cjs
node lib/canvas/agent-review.check.cjs
./node_modules/.bin/tsc --noEmit -p .
```

`make check` verifies schemas, routing, imports, dry-run dispatch, and Lambda packaging.
It may download build dependencies. These checks make no paid provider calls.
App behavior changes also require [real browser verification](docs/BROWSER_E2E.md)
through Comet with the real backend.

## Repository map

| Directory | Purpose |
| --- | --- |
| `studio/` | Next.js canvas, agent workspace, timeline, and design capture tests |
| `server/` | FastAPI, authentication, billing, uploads, and project persistence |
| `agent/` | Codex harness, optional Deep Agents backend, skills, and shared execution policy |
| `providers/` | Typed media integrations, rendering, inspection, and export |
| `remotion/` | Shared compositions and Lambda render site |
| `configs/`, `lambdas/`, `agentcore/`, `infra/` | Gateway schemas and deployment infrastructure |
| `tests/`, `scripts/` | Regression tests, local tooling, and deployment commands |
| `docs/` | [Current guides and provider references](docs/README.md) |

## Deploy

Deploy commands require configured AWS credentials and deployment access:

```bash
make gateway      # Provider Lambdas and Gateway targets
make runtime      # AgentCore Runtime
make smoke        # Runtime smoke test
```

`AGENTCORE_RUNTIME_ARN` selects the remote agent runtime. With it unset, the agent runs
in the backend process. Both paths use the configured Gateway.

Remotion composition changes need a matching site deployment:

```bash
npm ci --prefix remotion
npm run typecheck --prefix remotion
.venv/bin/python scripts/deploy_media_updates.py
```

See [media rendering and recovery](docs/MEDIA_RENDERING.md),
[third-party notices](THIRD_PARTY_NOTICES) before operating a deployment.
