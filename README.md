# Renderhaus Agent

Basic LangChain agent wired to generation MCP servers.

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
