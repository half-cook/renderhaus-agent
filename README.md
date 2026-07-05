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

Seedance and Gemini TTS are dry-run local MCPs for now. Existing provider MCPs are wired through
`configs/mcp.local.json`.
