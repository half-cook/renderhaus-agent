# Renderhaus

An AI-native video editor: a Next.js timeline editor (`web/`) in front of a Python
generation/agent backend (`server/`, `agent/`, `providers/`).

## Structure

- **`web/`** — Next.js editor frontend. Multi-track timeline, Remotion/WebCodecs preview, the
  manual-editing engine, and (as of the merge) the generation/library/production panels that used
  to live in a separate app. Product plan and architecture: [design/ARCHITECTURE.md](design/ARCHITECTURE.md).
- **`server/`** — FastAPI backend: Clerk auth, S3/DynamoDB asset storage, project/timeline
  persistence, generation job endpoints. Talked to over HTTP by `web/`, proxied at `/api/*` in dev
  (see `web/next.config.ts`).
- **`agent/`** — OpenAI Agents SDK manager; runs in-process locally or on Amazon Bedrock
  AgentCore Runtime.
- **`providers/`** — Seedance, Seedream, Mureka, Fish Audio, and Remotion implementations.
  AgentCore Gateway Lambdas call these; the Runtime agent never hosts them locally.
- **`docs/`** — the long-video production-agent program (below).
- **`design/`** — planning/status docs for how `web/` and `server/` came to live in one repo:
  [design/MERGE_STATUS.md](design/MERGE_STATUS.md) (start here — current state, what's verified,
  known gaps), [design/MERGE_PLAN.md](design/MERGE_PLAN.md) (git mechanics),
  [design/PRODUCTION_READINESS.md](design/PRODUCTION_READINESS.md) (scale/architecture audit),
  [design/ARCHITECTURE.md](design/ARCHITECTURE.md) (product vision).

The Studio's workspace, canvas, immutable asset-version, provenance, and durable execution model is
documented in [docs/STUDIO_STATE.md](docs/STUDIO_STATE.md). The end-to-end Studio manager, media
playback, Remotion, UI, and operations guide is [docs/STUDIO_AGENT.md](docs/STUDIO_AGENT.md).

## Long-video program

The evidence-backed product, architecture, continuity, evaluation, and six-sprint delivery package
for evolving Renderhaus into a durable 60–180 second video-production agent starts at
[docs/README.md](docs/README.md).

## Development workflow

Day-to-day local + CI/CD map: [docs/development.md](docs/development.md).

```bash
make setup    # once
make check    # before push
make web      # backend API only (see "Run the app" below for the full two-process setup)
make gateway  # deploy Mureka Lambda + Gateway
make runtime  # deploy AgentCore Runtime
```

## Run the app

Two processes: the FastAPI backend and the Next.js frontend.

```bash
# backend — installs the Python project, starts the API on :8000
bash scripts/setup_agent.sh
.venv/bin/python -m server.app
```

```bash
# frontend — installs and starts the Next.js dev server on :3000,
# proxying /api/* to the backend above
cd web
npm install
npm run dev
```

Then open [http://localhost:3000](http://localhost:3000). The backend alone (`:8000`) now serves
JSON only — there's no bundled UI there anymore, `web/` is the UI.

### Secrets (AWS Secrets Manager)

Application secrets live in Secrets Manager (`renderhaus/app` by default). Sync from a local
env file, then keep only bootstrap keys locally:

```bash
.venv/bin/python scripts/sync_secrets.py --rewrite-bootstrap
```

`load_local_env()` reads `.env.local` for bootstrap (`AWS_REGION`, `RENDERHAUS_SECRETS_NAME`),
then loads the JSON secret into the process environment. AgentCore Runtime uses the same secret
via its execution role.

### AgentCore (cloud agent + MCPs)

The LangChain agent and generation MCPs (Seedance, Seedream, Mureka, Fish Audio) can run on
Amazon Bedrock AgentCore Runtime. The backend stays local (or on its own host) and calls the
runtime when `AGENTCORE_RUNTIME_ARN` is set.

```bash
# Requires Docker Desktop + AWS credentials with deploy access
.venv/bin/python scripts/sync_secrets.py --rewrite-bootstrap
.venv/bin/python scripts/deploy_agentcore.py --region us-east-1
.venv/bin/python scripts/smoke_agentcore.py
.venv/bin/python -m server.app
```

With `AGENTCORE_RUNTIME_ARN` set (from Secrets Manager or bootstrap), generation/poll calls go to
AgentCore. Leave it unset to keep the local in-process agent. Tools still require
`AGENTCORE_GATEWAY_URL`.

The backend exposes generation and refinement requests through a video-only agent boundary,
persists local job state under `.renderhaus/web-jobs/`, and serves completed MP4s through
job-scoped media URLs. `web/` is what drives it now instead of the old bundled UI.

`SEEDANCE_DRY_RUN=true` keeps the full flow in preview mode without creating a paid video task.
Set `SEEDANCE_DRY_RUN=false` in `.env.local` only when you intend to run live video generation.

### Remotion Lambda renders

The OpenAI canvas agent exposes `render_remotion_video` for assembling generated images, videos,
voiceovers, and music into one downloadable MP4. The render site reuses the same typed
`TimelineComposition` as the editor preview.

```bash
# Creates/updates the official Remotion IAM role, Lambda renderer, and S3 render site.
make remotion

# Renders the first successful multi-tool artifact set as an end-to-end smoke test.
make smoke-remotion
```

Deployment metadata is stored under `.renderhaus/remotion/deployment.json` for local runs. The
same non-secret runtime settings are synchronized into the configured `renderhaus/app` Secrets
Manager secret for AgentCore deployments. Remotion packages are pinned to the same exact version;
upgrade the NPM and Python packages together before redeploying the function and site.

## Setup

Populate `.env.local`, then run:

```bash
bash scripts/setup_agent.sh
```

### Clerk authentication

Each developer with access to the shared Clerk application can configure the Studio checkout
without exchanging keys:

```bash
make setup-clerk
```

This signs the developer into Clerk, links `studio/` to the application associated with this
repository, writes frontend credentials to the ignored `studio/.env.local`, and runs Clerk's
diagnostic check. A Clerk administrator must invite developers who do not yet have application
access. Never commit either `.env.local` file.

The backend uses the same Clerk application to verify sessions. Add its keys from the
[Clerk API keys](https://dashboard.clerk.com/last-active?path=api-keys) page to the root
`.env.local`, or provide them through AWS Secrets Manager:

```env
# Either name works for the publishable key
CLERK_PUBLISHABLE_KEY=pk_test_...
# NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
CLERK_AUTHORIZED_PARTIES=http://localhost:3000,http://127.0.0.1:3000,http://localhost:5174,http://127.0.0.1:5174,http://localhost:8000,http://127.0.0.1:8000
# Optional: PEM public key for networkless JWT verification (newlines as \n)
CLERK_JWT_KEY=
```

`localhost:3000` is the editor origin and `localhost:5174` is the Studio origin; their
`127.0.0.1` variants cover opening either UI through that hostname. The `:8000` entries cover
hitting the backend directly (docs, scripts, tests). Clerk compares this allowlist against the
session token's exact `azp` origin, including the port.

When both a publishable key and `CLERK_SECRET_KEY` are set, generation/upload APIs require a
signed-in session. Leave them empty to keep the local UI open during setup.

### Artifact storage

Generated media and reference uploads are owned by the signed-in Clerk user (or `local` when
Clerk is off).

- **Bytes:** Amazon S3 (`AWS_S3_BUCKET`), keys like `users/{user_id}/assets/{asset_id}/...`
- **Metadata:** DynamoDB table `AWS_DYNAMODB_ASSETS_TABLE` (default `renderhaus-assets`)
- **Playback:** job `media_url` is an opaque app URL that redirects to a short-lived S3
  presigned GET (`/api/assets/{id}/content?exp=...&sig=...`)

```env
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
AWS_S3_BUCKET=your-unique-bucket-name
AWS_DYNAMODB_ASSETS_TABLE=renderhaus-assets
# Optional HMAC secret for the opaque media URL
ASSET_SIGNING_SECRET=
```

On startup the app creates the DynamoDB table (and bucket, if missing) when credentials allow.
Reference images used by the agent are cached under `.renderhaus/cache/`.

## Check Secrets

```bash
.venv/bin/python -m agent.main --check-env
```

This only prints `set` or `empty`, never secret values.

## List MCP Tools

```bash
make tools
```

## Provider tools via AgentCore Gateway

Seedance, Seedream, Mureka, Fish Audio, and Remotion are Lambda targets behind one Amazon Bedrock
AgentCore Gateway. The Runtime agent is an MCP client of that URL. There is no local MCP process.

```bash
.venv/bin/python scripts/deploy_gateway.py --region us-east-1
# Writes .env.agentcore.gateway with AGENTCORE_GATEWAY_URL
# Sync that URL into Secrets Manager, then:
.venv/bin/python scripts/deploy_agentcore.py --region us-east-1
```

`AGENTCORE_GATEWAY_URL` is required. The agent does not spawn provider MCP servers.

## Supervisor (Director + Executor)

Multi-shot flow: Director plans → you approve → Executor runs modality workers.

```bash
make supervise ARGS='30s product teaser with calm piano BGM'
make supervise ARGS='30s product teaser with calm piano BGM' EXECUTE=1
```

In the web UI, use the **Production** tab: brief → plan → **Approve & run**.
API: `POST /api/productions`, `POST /api/productions/{id}/commands/approve-plan`.

The Director emits a typed plan only; the Executor deterministically calls modality workers. This is
not an LLM swarm over paid tools.

## Run A Prompt

```bash
.venv/bin/python -m agent.main "List the generation tools you can use and propose a 10 second product-video workflow."
```

## Headless Generation Runner

```bash
.venv/bin/python -m agent.generate models
.venv/bin/python -m agent.generate video "simple abstract blue and white AI video editor timeline animation"
```

Generation job records are written under `.renderhaus/jobs/`.

Seedance video generation is live when `SEEDANCE_DRY_RUN=false`; Fish Audio TTS is live when
`FISH_AUDIO_DRY_RUN=false`.
