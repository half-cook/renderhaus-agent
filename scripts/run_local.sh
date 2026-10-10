#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
if [[ ! -x .venv/bin/python ]]; then
    echo "MissingVenv: run make setup (or bash scripts/setup_agent.sh) with Python >=3.11." >&2
    exit 1
fi
exec .venv/bin/python scripts/local_env.py "$@"
