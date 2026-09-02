# Renderhaus local shortcuts. Prefer these over remembering long python commands.
PYTHON ?= .venv/bin/python
REGION ?= us-east-1
PROVIDER ?= all

.PHONY: help setup setup-clerk check lint tools backend studio dry-flags gateway smoke-gateway runtime smoke deploy-all invoke-tool schemas smoke-remotion

help:
	@echo "Local development"
	@echo "  make setup         Create venv + install deps"
	@echo "  make check         Fast CI checks (no paid APIs)"
	@echo "  make lint          Ruff check"
	@echo "  make tools         List Gateway tools generated from providers/"
	@echo "  make schemas       Write configs/gateway/*.tools.json from provider APIs"
	@echo "  make studio        Next.js canvas UI (the app) -- needs make backend too"
	@echo "  make backend       FastAPI backend API on :8000"
	@echo "  make setup-clerk  Link this checkout to the shared Clerk app"
	@echo "  make dry-flags     Print dry-run flags the process sees"
	@echo "  make invoke-tool   Local Lambda-shaped invoke (PROVIDER=seedance TOOL=list_seedance_models)"
	@echo ""
	@echo "Deploy (needs AWS creds)"
	@echo "  make gateway         Deploy Gateway Lambdas + targets (PROVIDER=all|seedance|...)"
	@echo "  make smoke-gateway   Build the Lambda zip without uploading"
	@echo "  make runtime         Build/push/deploy AgentCore Runtime"
	@echo "  make smoke           Smoke-test AgentCore runtime"
	@echo "  make smoke-remotion  Render the first multi-tool artifacts through the deployed Remotion Lambda"
	@echo "  make deploy-all      gateway + runtime + smoke"

setup:
	bash scripts/setup_agent.sh

check:
	$(PYTHON) scripts/ci_check.py

lint:
	$(PYTHON) -m ruff check agent lambdas scripts server providers

tools:
	$(PYTHON) scripts/generate_gateway_schemas.py --list --provider $(PROVIDER)

schemas:
	$(PYTHON) scripts/generate_gateway_schemas.py --provider $(PROVIDER)

backend:
	$(PYTHON) -m server.app

studio:
	cd studio && npm run dev

setup-clerk:
	cd studio && npx -y clerk@latest init --login --no-skills
	cd studio && npx -y clerk@latest doctor

invoke-tool:
	$(PYTHON) scripts/invoke_tool.py --provider $(PROVIDER) --tool $(TOOL) --args '$(or $(ARGS),{})'

dry-flags:
	@$(PYTHON) -c "from server.config import load_local_env; import os; load_local_env();\
keys=['SEEDANCE_DRY_RUN','SEEDREAM_DRY_RUN','MUREKA_DRY_RUN','FISH_AUDIO_DRY_RUN','REMOTION_DRY_RUN','AGENTCORE_RUNTIME_ARN','AGENTCORE_GATEWAY_URL'];\
[print(f'{k}={os.getenv(k)!r}') for k in keys]"

gateway:
	$(PYTHON) scripts/deploy_gateway.py --region $(REGION) --provider $(PROVIDER)

smoke-gateway:
	$(PYTHON) scripts/deploy_gateway.py --build-zip-only

runtime:
	$(PYTHON) scripts/deploy_agentcore.py --region $(REGION)

smoke:
	$(PYTHON) scripts/smoke_agentcore.py

smoke-remotion:
	$(PYTHON) scripts/smoke_remotion_lambda.py

deploy-all: gateway runtime smoke
