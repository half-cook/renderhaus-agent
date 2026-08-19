# Renderhaus local shortcuts. Prefer these over remembering long python commands.
PYTHON ?= .venv/bin/python
REGION ?= us-east-1
PROVIDER ?= all

.PHONY: help setup check lint tools web studio dry-flags gateway smoke-gateway runtime smoke deploy-all invoke-tool schemas

help:
	@echo "Local development"
	@echo "  make setup         Create venv + install deps"
	@echo "  make check         Fast CI checks (no paid APIs)"
	@echo "  make lint          Ruff check"
	@echo "  make tools         List Gateway tools generated from providers/"
	@echo "  make schemas       Write configs/gateway/*.tools.json from provider APIs"
	@echo "  make studio        Canvas UI for calling MCP tools locally (needs make web too)"
	@echo "  make dry-flags     Print dry-run flags the process sees"
	@echo "  make invoke-tool   Local Lambda-shaped invoke (PROVIDER=seedance TOOL=list_seedance_models)"
	@echo ""
	@echo "Deploy (needs AWS creds)"
	@echo "  make gateway         Deploy Gateway Lambdas + targets (PROVIDER=all|seedance|...)"
	@echo "  make smoke-gateway   Build the Lambda zip without uploading"
	@echo "  make runtime         Build/push/deploy AgentCore Runtime"
	@echo "  make smoke           Smoke-test AgentCore runtime"
	@echo "  make deploy-all      gateway + runtime + smoke"

setup:
	bash scripts/setup_agent.sh

check:
	$(PYTHON) scripts/ci_check.py

lint:
	$(PYTHON) -m ruff check agent mcps lambdas scripts server providers

tools:
	$(PYTHON) scripts/generate_gateway_schemas.py --list --provider $(PROVIDER)

schemas:
	$(PYTHON) scripts/generate_gateway_schemas.py --provider $(PROVIDER)

web:
	$(PYTHON) -m server.app

studio:
	cd studio && npm run dev

invoke-tool:
	$(PYTHON) scripts/invoke_tool.py --provider $(PROVIDER) --tool $(TOOL) --args '$(or $(ARGS),{})'

dry-flags:
	@$(PYTHON) -c "from server.config import load_local_env; import os; load_local_env();\
keys=['SEEDANCE_DRY_RUN','SEEDREAM_DRY_RUN','MUREKA_DRY_RUN','GEMINI_TTS_DRY_RUN','AGENTCORE_RUNTIME_ARN','AGENTCORE_GATEWAY_URL'];\
[print(f'{k}={os.getenv(k)!r}') for k in keys]"

gateway:
	$(PYTHON) scripts/deploy_gateway.py --region $(REGION) --provider $(PROVIDER)

smoke-gateway:
	$(PYTHON) scripts/deploy_gateway.py --build-zip-only

runtime:
	$(PYTHON) scripts/deploy_agentcore.py --region $(REGION)

smoke:
	$(PYTHON) scripts/smoke_agentcore.py

deploy-all: gateway runtime smoke
