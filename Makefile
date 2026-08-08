# Renderhaus local shortcuts. Prefer these over remembering long python commands.
PYTHON ?= .venv/bin/python
REGION ?= us-east-1

.PHONY: help setup check lint tools web local-agent dry-flags gateway runtime smoke deploy-all supervise

help:
	@echo "Local development"
	@echo "  make setup       Create venv + install deps"
	@echo "  make check       Fast CI checks (no paid APIs)"
	@echo "  make lint        Ruff check"
	@echo "  make tools       List MCP tools"
	@echo "  make web         Run the backend API only (turn off AgentCore ARN for pure local;"
	@echo "                   for the full editor UI, also run the Next.js app under web/ -- see README)"
	@echo "  make local-agent Run one CLI prompt (ARGS='your prompt')"
	@echo "  make supervise   Director plan (ARGS='brief'); add EXECUTE=1 to run workers"
	@echo "  make dry-flags   Print dry-run flags the process sees"
	@echo ""
	@echo "Deploy (needs AWS creds)"
	@echo "  make gateway     Deploy Mureka Lambda + AgentCore Gateway"
	@echo "  make runtime     Build/push/deploy AgentCore Runtime"
	@echo "  make smoke       Smoke-test AgentCore runtime"
	@echo "  make deploy-all  gateway + runtime + smoke"

setup:
	bash scripts/setup_agent.sh

check:
	$(PYTHON) scripts/ci_check.py

lint:
	$(PYTHON) -m ruff check agent mcps lambdas scripts

tools:
	$(PYTHON) -m agent.main --list-tools

web:
	$(PYTHON) -m server.app

local-agent:
	$(PYTHON) -m agent.main $(ARGS)

supervise:
	$(PYTHON) -m agent.supervise $(ARGS) $(if $(EXECUTE),--execute,) --local-only

dry-flags:
	@$(PYTHON) -c "from agent.config import load_local_env; import os; load_local_env();\
keys=['SEEDANCE_DRY_RUN','SEEDREAM_DRY_RUN','MUREKA_DRY_RUN','GEMINI_TTS_DRY_RUN','AGENTCORE_RUNTIME_ARN','AGENTCORE_GATEWAY_URL'];\
[print(f'{k}={os.getenv(k)!r}') for k in keys]"

gateway:
	$(PYTHON) scripts/deploy_mureka_gateway.py --region $(REGION)

runtime:
	$(PYTHON) scripts/deploy_agentcore.py --region $(REGION)

smoke:
	$(PYTHON) scripts/smoke_agentcore.py

deploy-all: gateway runtime smoke
