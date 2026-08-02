# Renderhaus Agent

Basic LangChain agent wired to generation MCP servers.

## Long-video program

The evidence-backed product, architecture, continuity, evaluation, and six-sprint delivery package
for evolving Renderhaus into a durable 60–180 second video-production agent starts at
[docs/README.md](docs/README.md).

## Run the web app

Install the project and start the local Renderhaus UI:

```bash
bash scripts/setup_agent.sh
.venv/bin/python -m web.app
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

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

The LangChain agent and generation MCPs (Seedance, Seedream, Mureka, Gemini TTS) can run on
Amazon Bedrock AgentCore Runtime. The web app stays local (or on its own host) and calls the
runtime when `AGENTCORE_RUNTIME_ARN` is set.

```bash
# Requires Docker Desktop + AWS credentials with deploy access
.venv/bin/python scripts/sync_secrets.py --rewrite-bootstrap
.venv/bin/python scripts/deploy_agentcore.py --region us-east-1
.venv/bin/python scripts/smoke_agentcore.py
.venv/bin/python -m web.app
```

With `AGENTCORE_RUNTIME_ARN` set (from Secrets Manager or bootstrap), generation/poll calls go to
AgentCore. Leave it unset to keep the local in-process agent + stdio MCPs.

The web app provides the minimal prompt → create → review workflow. It sends generation and
refinement requests through a video-only agent boundary, persists local job state under
`.renderhaus/web-jobs/`, and serves completed MP4s through job-scoped media URLs.

`SEEDANCE_DRY_RUN=true` keeps the full UI and agent flow in preview mode without creating a paid
video task. Set `SEEDANCE_DRY_RUN=false` in `.env.local` only when you intend to run live video
generation.

## Setup

Populate `.env.local`, then run:

```bash
bash scripts/setup_agent.sh
```

### Clerk authentication

The web app uses [Clerk](https://clerk.com) for sign-in. Add keys from the
[Clerk API keys](https://dashboard.clerk.com/last-active?path=api-keys) page to `.env.local`:

```env
# Either name works for the publishable key
CLERK_PUBLISHABLE_KEY=pk_test_...
# NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
CLERK_AUTHORIZED_PARTIES=http://127.0.0.1:8000,http://localhost:8000
# Optional: PEM public key for networkless JWT verification (newlines as \n)
CLERK_JWT_KEY=
```

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
.venv/bin/python -m agent.main --list-tools
```

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

Existing provider MCPs are wired through `configs/mcp.local.json`. Seedance video generation is live
when `SEEDANCE_DRY_RUN=false`; Gemini TTS is still a local dry-run MCP.
