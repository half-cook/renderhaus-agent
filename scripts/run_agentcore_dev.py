#!/usr/bin/env python3
"""Start the local AgentCore runtime for agent/studio_agent_next.py."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.config import load_local_env  # noqa: E402


def main() -> int:
    load_local_env()
    os.chdir(ROOT)
    npm_bin = Path.home() / ".npm-global" / "bin"
    os.environ["PATH"] = str(npm_bin) + os.pathsep + os.environ.get("PATH", "")
    os.execvp(
        "agentcore",
        [
            "agentcore",
            "dev",
            "--logs",
            "--port",
            "8080",
            "--no-browser",
            "--skip-deploy",
            "--no-traces",
        ],
    )


if __name__ == "__main__":
    raise SystemExit(main())
