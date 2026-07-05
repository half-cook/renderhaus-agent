#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e . uv

mkdir -p .external/mcps
if [ ! -d ".external/mcps/gpt-image-2-mcp/.git" ]; then
  git clone https://github.com/Borys520/gpt-image-2-mcp.git .external/mcps/gpt-image-2-mcp
fi

cd .external/mcps/gpt-image-2-mcp
pnpm install || {
  pnpm approve-builds --all
  pnpm install
}
pnpm run build
