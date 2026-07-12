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
